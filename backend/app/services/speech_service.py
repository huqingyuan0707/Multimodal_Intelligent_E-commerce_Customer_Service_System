"""语音 ASR/TTS 单出口（对齐 FR-1.3 + 执行步骤 A）

链路：transcribe(音频→{text, confidence, need_confirm}) → 低置信回问确认；
      synthesize(文本→{voice, enabled}) → 前端波形播放 + 文字对照。
单出口口径：业务只认 transcribe()/synthesize()/tts_config()/probe()，
             网关（SenseVoice/edge-tts）接入只改 Settings，不动业务。
降级红线：ASR 不可用 → 文件名规则转写 + degraded=True，绝不 500；
           TTS 关闭 → 返回 enabled=False，前端只显文字对照。
"""

from __future__ import annotations

import time

import httpx

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record

# ---------------- 常量 ----------------

AUDIO_TYPES: tuple[str, ...] = ("audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg", "audio/webm")


# ---------------- 转写 ----------------


def precheck_audio(*, filename: str, content_type: str, size: int) -> None:
    """语音预检：空文件/超 5M 报 1001；类型不在白名单 1001。"""
    if size <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请先录制一段语音", 400)
    if size > settings.VOICE_MAX_BYTES:
        raise BusinessError(ErrorCode.PARAM_INVALID, "语音过大，请控制在 60 秒内重试", 400)
    if content_type and content_type not in set(AUDIO_TYPES):
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅支持 Mp3/Wav/M4A/Opus 语音", 400)
    _ = filename


def stub_transcribe(*, filename: str, size: int) -> dict[str, object]:
    """规则转写降级：文件名含退/破/换 → 售后话术 0.82；否则通用咨询 0.55 待确认。"""
    name = filename or ""
    if any(k in name for k in ("退", "破", "换", "瑕疵", "refund")):
        text, confidence = "这件衣服有破洞要退货", 0.82
    else:
        text, confidence = "你好，我想咨询一下这件衣服", 0.55
    _ = size
    return {
        "text": text,
        "confidence": confidence,
        "need_confirm": confidence < settings.ASR_CONFIDENCE_THRESHOLD,
        "degraded": True,
    }


class AsrUnavailableError(Exception):
    """ASR 不可用（调用方转 stub 降级，不冒泡 500）。"""


async def _post_audio(
    url: str,
    files: dict[str, tuple[str, bytes, str]],
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    """唯一的 ASR POST 出口（OpenAI 兼容 multipart；测试在此打桩）。"""
    async with httpx.AsyncClient(timeout=settings.ASR_TIMEOUT_SECONDS, trust_env=False) as client:
        return await client.post(url, files=files, data=data, headers=headers)


def _confidence_from_verbose(body: dict[str, object]) -> float:
    """verbose_json → 置信度（纯函数）：优先 no_speech_prob 均值，其次 avg_logprob 指数。

    段缺失时回 0.7（未知按中等置信交阈值判定，不硬答不硬转）。
    """
    segments = body.get("segments")
    if not isinstance(segments, list) or not segments:
        return 0.7
    probs: list[float] = []
    use_speech = False
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        no_speech = seg.get("no_speech_prob")
        if isinstance(no_speech, (int, float)) and not isinstance(no_speech, bool):
            use_speech = True
            probs.append(max(0.0, min(1.0, 1.0 - float(no_speech))))
    if use_speech and probs:
        return round(sum(probs) / len(probs), 2)
    logs: list[float] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        avg = seg.get("avg_logprob")
        if isinstance(avg, (int, float)) and not isinstance(avg, bool):
            import math

            logs.append(max(0.0, min(1.0, math.exp(float(avg)))))
    if logs:
        return round(sum(logs) / len(logs), 2)
    return 0.7


def _parse_asr_result(body: object) -> dict[str, object]:
    """解析网关转写结果（纯函数可单测）：空文本视为不可用抛错走 stub。"""
    if not isinstance(body, dict):
        raise AsrUnavailableError("ASR 响应结构异常（顶层非对象）")
    text = str(body.get("text", "")).strip()
    if not text:
        raise AsrUnavailableError("ASR 返回空文本")
    confidence = _confidence_from_verbose(body)
    return {
        "text": text,
        "confidence": confidence,
        "need_confirm": confidence < settings.ASR_CONFIDENCE_THRESHOLD,
        "degraded": False,
    }


async def transcribe(
    *, filename: str, content_type: str, size: int, audio: bytes | None = None
) -> dict[str, object]:
    """转写主入口：预检 → 在线 ASR（真声 OpenAI 兼容 /audio/transcriptions）→ 失败转 stub。

    audio 为上传字节（端点透传）；None 时沿用“连通性探测 + 文件名 stub”（兼容历史行为）。
    一律返回 {text, confidence, need_confirm, degraded}。
    """
    precheck_audio(filename=filename, content_type=content_type, size=size)
    if not settings.ASR_ENABLED or not audio:
        return stub_transcribe(filename=filename, size=size)
    url = settings.ASR_BASE_URL.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.ASR_API_KEY.get_secret_value()}"}
    started = time.perf_counter()
    try:
        resp = await _post_audio(
            url,
            files={"file": (filename or "voice.webm", audio, content_type or "audio/webm")},
            data={
                "model": settings.ASR_MODEL,
                "response_format": "verbose_json",
                "temperature": "0",
            },
            headers=headers,
        )
    except (httpx.HTTPError, OSError) as exc:
        record("asr", {"ok": False, "degraded": str(exc)[:120]})
        return stub_transcribe(filename=filename, size=size)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code >= 400:
        record("asr", {"ok": False, "latency_ms": latency_ms})
        return stub_transcribe(filename=filename, size=size)
    try:
        body = resp.json()
    except ValueError as exc:
        record("asr", {"ok": False, "latency_ms": latency_ms})
        raise AsrUnavailableError("ASR 响应非 JSON") from exc
    try:
        out = _parse_asr_result(body)
    except AsrUnavailableError as exc:
        record("asr", {"ok": False, "degraded": str(exc)[:120]})
        return stub_transcribe(filename=filename, size=size)
    record(
        "asr",
        {
            "ok": True,
            "latency_ms": latency_ms,
            "model": settings.ASR_MODEL,
            "confidence": out.get("confidence", 0.0),
        },
    )
    return out


# ---------------- 合成 ----------------


def tts_config() -> dict[str, object]:
    """TTS 开关/音色（前端下拉与播放开关同源，Settings 唯一口径）。"""
    return {
        "enabled": settings.TTS_ENABLED,
        "voice": settings.TTS_VOICE,
        "voices": list(settings.TTS_VOICES),
    }


def synthesize(*, text: str, voice: str = "") -> dict[str, object]:
    """合成 stub：返回文本 + 音色，前端用 WebSpeech 播放 + 波形（无二进制不断流）。

    voice 为空用默认晓晓；不在白名单 1001；TTS 关闭时 enabled=False 只回文字。
    """
    cleaned = (text or "").strip()[:500]
    if not cleaned:
        raise BusinessError(ErrorCode.PARAM_INVALID, "合成文本不能为空", 400)
    picked = (voice or settings.TTS_VOICE).strip() or settings.TTS_VOICE
    if picked not in set(settings.TTS_VOICES):
        raise BusinessError(ErrorCode.PARAM_INVALID, "不支持该音色", 400)
    if not settings.TTS_ENABLED:
        return {"text": cleaned, "voice": picked, "enabled": False, "degraded": True}
    return {"text": cleaned, "voice": picked, "enabled": True, "degraded": False}


async def probe() -> dict[str, object]:
    """可用性巡检（/governance/status 加法字段，不抛异常）。"""
    base: dict[str, object] = {
        "provider": "asr",
        "model": settings.ASR_MODEL,
        "base_url": settings.ASR_BASE_URL,
        "enabled": settings.ASR_ENABLED,
        "threshold": settings.ASR_CONFIDENCE_THRESHOLD,
        "tts": tts_config(),
    }
    if not settings.ASR_ENABLED:
        return {**base, "available": False, "detail": "ASR_ENABLED=false，转写走规则降级"}
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(settings.ASR_BASE_URL.rstrip("/") + "/models")
    except (httpx.HTTPError, OSError):
        return {**base, "available": False, "detail": "ASR 不可达，转写走规则降级（不中断）"}
    if resp.status_code >= 400:
        return {**base, "available": False, "detail": f"ASR 返回 HTTP {resp.status_code}"}
    return {**base, "available": True, "detail": "ASR 在线"}
