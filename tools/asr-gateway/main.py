"""SenseVoice ASR 网关（OpenAI 兼容独立进程，对齐 FR-1.3 + 执行步骤 A + speech_service 单出口）

链路：backend speech_service.transcribe --multipart--> 本网关 /v1/audio/transcriptions
      → FunASR AutoModel(SenseVoiceSmall) 转写 → {"text", "segments": []} 回包；
      GET /v1/models 供 /governance/status 的 probe() 探测，/healthz 供容器探活。
协议口径：multipart 字段（file/model/response_format/temperature）与
         speech_service._post_audio 严格对齐；SenseVoice 无逐段置信输出，回空
         segments → 调用侧置信度走「中等默认 0.7」（speech_service.
         _confidence_from_verbose 口径），低置信回问链路由 ASR_CONFIDENCE_THRESHOLD 兜底。
降级红线：模型未就绪/转写异常回 HTTP 5xx → backend 自动转 stub 降级，绝不阻塞客服链路。
启动（backend 外独立进程，端口 8100 避开 8000 后端与 11434 Ollama）：
  pip install -r requirements.txt
  uvicorn main:app --host 127.0.0.1 --port 8100
  首启自动下载模型（~1GB，走 HF_ENDPOINT 镜像加速）；需系统 ffmpeg 解码 webm/m4a。
接通：backend/.env 改 ASR_BASE_URL=http://127.0.0.1:8100/v1 即生效；
      网关未启动时 backend 自动 stub 降级（speech_service 既有行为，无感回退）。
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

# 模型下载镜像（对齐 backend 红线：模型下载前设 HF_ENDPOINT；可被环境变量覆盖）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

MODEL_ID = "iic/SenseVoiceSmall"
MODEL_ALIAS = "sensevoice-small"
# SenseVoice rich_text 前缀 tag（<|zh|><|NEUTRAL|><|Speech|><|woitn|>），只留纯文本
_RICH_TAG = re.compile(r"<\|[^|]*\|>")

_state: dict[str, object] = {"model": None, "err": ""}
_lock = threading.Lock()


def _get_model() -> object:
    """惰性单例双检锁加载（对齐 backend 并发红线；阻塞加载放 to_thread 调用方侧）。"""
    if _state["model"] is None:
        with _lock:
            if _state["model"] is None:
                try:
                    from funasr import AutoModel

                    _state["model"] = AutoModel(
                        model=MODEL_ID, trust_remote_code=False, disable_update=True
                    )
                    _state["err"] = ""
                except Exception as exc:  # 模型下载失败/缺依赖：留 err 供 /healthz 与 503 明示
                    _state["err"] = f"{exc.__class__.__name__}: {exc}"[:200]
                    raise
    return _state["model"]


def _transcribe_sync(path: str) -> str:
    """同步转写（FunASR 阻塞推理），剥 rich_text tag 只回纯文本。"""
    model = _get_model()
    res = model.generate(input=path, cache={}, language="auto", use_itn=True)
    text = ""
    if isinstance(res, list) and res:
        text = str(res[0].get("text", ""))
    elif isinstance(res, dict):
        text = str(res.get("text", ""))
    return _RICH_TAG.sub("", text).strip()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """启动即预热模型（失败不退出：/healthz 报 err，请求时 503，backend 侧自动降级）。"""
    with suppress(Exception):
        await asyncio.to_thread(_get_model)
    yield


app = FastAPI(title="reai-asr-gateway", version="1.0.0", lifespan=_lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """探活：模型就绪 ok=true；err 带首启失败原因（下载断网/缺 ffmpeg 等）。"""
    return {"ok": _state["model"] is not None, "model": MODEL_ALIAS, "err": _state["err"]}


@app.get("/v1/models")
async def models() -> dict[str, object]:
    """OpenAI 兼容模型列表（backend probe() 探测此端点判「ASR 在线」）。"""
    return {
        "object": "list",
        "data": [{"id": MODEL_ALIAS, "object": "model", "owned_by": "funasr"}],
    }


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = MODEL_ALIAS,
    response_format: Annotated[str, Form()] = "json",
    temperature: Annotated[str, Form()] = "0",
) -> dict[str, object]:
    """OpenAI 兼容转写：multipart(file/model/response_format) → {"text", "segments"}。

    temperature 为兼容字段（Whisper 协议带，SenseVoice 贪心解码恒 0，仅接不读）。
    """
    _ = model, temperature
    if _state["model"] is None:
        try:
            await asyncio.to_thread(_get_model)
        except Exception:
            raise HTTPException(status_code=503, detail=f"模型未就绪：{_state['err']}") from None
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    started = time.perf_counter()
    try:
        raw = await file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
    finally:
        await file.close()
    try:
        text = await asyncio.to_thread(_transcribe_sync, tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"转写失败：{exc.__class__.__name__}") from exc
    finally:
        with suppress(OSError):
            os.unlink(tmp_path)
    latency_ms = int((time.perf_counter() - started) * 1000)
    # segments 留空：SenseVoice 无逐段置信，调用侧走「中等默认 0.7」口径（见文件头）
    out: dict[str, object] = {"text": text, "segments": [], "latency_ms": latency_ms}
    if response_format not in ("verbose_json", "json"):
        out = {"text": text}
    return out
