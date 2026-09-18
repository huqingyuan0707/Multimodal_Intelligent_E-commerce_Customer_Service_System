"""多模态链路单测（FR-1 图文售后 + 语音，对齐 FRD §6/§7 + 执行步骤 A）

覆盖：图片预检（类型/超限 2004）→ NSFW 预检（2003）→ stub 定级/低置信转人工 →
真图缩放/结构化解析/网关打桩 → 清洗钳制 + need_human 重算 → 上下文含定级/方案/时效 →
语音转写/合成阈值 + 网关 verbose_json 解析 → 对象存储落盘回读隔离。
运行（backend/ 目录）：pytest tests/test_multimodal.py
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.services import chat_service, media_store, speech_service, vision_service


def _png_bytes(color: str = "red", size: tuple[int, int] = (8, 8)) -> bytes:
    """测试像素图（PIL 现场生成，不依赖外部文件）。"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _resp(status: int, body: Any) -> httpx.Response:
    request = httpx.Request("POST", "http://test/v1/chat/completions")
    if isinstance(body, dict):
        return httpx.Response(status, json=body, request=request)
    return httpx.Response(status, text=str(body), request=request)


# ---------------- 图片预检 ----------------


def test_precheck_rejects_type() -> None:
    """非 JPG/PNG/WEBP 报 1001 中文提示。"""
    with pytest.raises(BusinessError) as exc:
        vision_service.precheck(filename="a.gif", content_type="image/gif", size=100)
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_precheck_rejects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    """超 10M 报 2004（FR-1.2 超限码，前端压缩兜底后仍被拒收）。"""
    monkeypatch.setattr(settings, "IMAGE_MAX_BYTES", 10)
    with pytest.raises(BusinessError) as exc:
        vision_service.precheck(filename="a.jpg", content_type="image/jpeg", size=11)
    assert exc.value.code == ErrorCode.IMAGE_TOO_LARGE


async def test_inspect_unsafe_filename_raises_2003() -> None:
    """NSFW/PII 命中直接 2003，不进 VLM 不硬答。"""
    with pytest.raises(BusinessError) as exc:
        await vision_service.inspect_image(
            filename="nsfw-face.jpg", content_type="image/jpeg", size=100
        )
    assert exc.value.code == ErrorCode.UNSAFE_CONTENT


async def test_inspect_degraded_stub_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    """VLM 关闭时文件名关键词 → 破洞 0.85 不转人工（演示不断流）。"""
    monkeypatch.setattr(settings, "VLM_ENABLED", False)
    result = await vision_service.inspect_image(
        filename="破洞-袖口.jpg", content_type="image/jpeg", size=100
    )
    assert result.category == "破洞"
    assert result.confidence == 0.85
    assert result.need_human is False
    assert result.degraded is True


async def test_inspect_unknown_low_confidence_turns_human(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无命中 → 无瑕疵 0.55 必转人工（置信 <0.6 不硬答红线）。"""
    monkeypatch.setattr(settings, "VLM_ENABLED", False)
    result = await vision_service.inspect_image(
        filename="normal.jpg", content_type="image/jpeg", size=100
    )
    assert result.category == "无瑕疵"
    assert result.need_human is True


# ---------------- 真图链路 ----------------


def test_downscale_returns_jpeg_data_url() -> None:
    """真图预处理：统一转 JPEG data URL（网关 image_url 直用）。"""
    url = vision_service._downscale_image(_png_bytes())
    assert url.startswith("data:image/jpeg;base64,")


def test_downscale_invalid_bytes_unavailable() -> None:
    """损坏图片抛不可用 → 调用方转 stub，绝不 500。"""
    with pytest.raises(vision_service.VisionUnavailableError):
        vision_service._downscale_image(b"not-an-image")


def test_parse_vlm_json_structured() -> None:
    """结构化输出：类别/置信度/描述/bbox 全解析，不转人工。"""
    result = vision_service._parse_vlm_result(
        '{"category":"破洞","confidence":0.9,"desc":"袖口裂口","bbox":[0.1,0.2,0.3,0.4]}'
    )
    assert result.category == "破洞"
    assert result.confidence == 0.9
    assert result.need_human is False
    assert result.degraded is False
    assert result.bbox == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}


def test_parse_vlm_json_keyword_fallback() -> None:
    """非 JSON 但含类别词 → 兜底 0.55 必转人工；无信号抛错。"""
    fallback = vision_service._parse_vlm_result("看着像有个破洞")
    assert fallback.category == "破洞" and fallback.need_human is True
    with pytest.raises(vision_service.VisionUnavailableError):
        vision_service._parse_vlm_result("一切正常谢谢")


def test_parse_vlm_truncated_json_recovers_fields() -> None:
    """截断 JSON（小模型 desc 写一半）：类别/置信度逐字段回收。"""
    result = vision_service._parse_vlm_result(
        '{"category":"色差","confidence":0.88,"desc":"左右存在明显'
    )
    assert result.category == "色差"
    assert result.confidence == 0.88
    assert result.need_human is False


async def test_vlm_call_posts_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """网关打桩：image_url 真图 + JSON 解析走在线路（degraded=False）。"""
    seen: dict[str, Any] = {}

    async def _fake(url: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        seen.update(payload)
        return _resp(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"category":"污渍","confidence":0.8,"desc":"领口污渍"}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(vision_service, "_post_json", _fake)
    monkeypatch.setattr(settings, "VLM_PROTOCOL", "openai")
    result = await vision_service._vlm_call(filename="a.jpg", image=_png_bytes())
    assert result.category == "污渍" and result.degraded is False
    parts = seen["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in parts)


async def test_vlm_call_ollama_native_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama 原生分支：/api/chat 形状解析 + think 开关透传。"""
    seen: dict[str, Any] = {}

    async def _fake(url: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        seen.update(payload)
        assert url.endswith("/api/chat")
        return _resp(
            200, {"message": {"content": '{"category":"开线","confidence":0.7,"desc":"缝线裂开"}'}}
        )

    monkeypatch.setattr(settings, "VLM_PROTOCOL", "ollama")
    monkeypatch.setattr(vision_service, "_post_json", _fake)
    result = await vision_service._vlm_call(filename="a.jpg", image=_png_bytes())
    assert result.category == "开线" and result.degraded is False
    assert seen["think"] is False


async def test_inspect_image_bytes_vlm_disabled_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有字节但 VLM 关闭 → 仍走 stub（签名向后兼容）。"""
    monkeypatch.setattr(settings, "VLM_ENABLED", False)
    result = await vision_service.inspect_image(
        filename="破洞.jpg", content_type="image/jpeg", size=100, image=_png_bytes()
    )
    assert result.category == "破洞" and result.degraded is True


# ---------------- 清洗与上下文 ----------------


def test_sanitize_recomputes_need_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """不信任前端 need_human：按阈值重算 + 非法类别归无瑕疵 + 越界钳制。"""
    monkeypatch.setattr(settings, "VLM_CONFIDENCE_THRESHOLD", 0.6)
    cleaned = chat_service.sanitize_inspections(
        [
            {"category": "破洞", "confidence": 0.9, "need_human": True},
            {"category": "外星瑕疵", "confidence": 9.9, "desc": "x"},
        ],
        settings.IMAGE_MAX_COUNT,
    )
    assert cleaned[0]["need_human"] is False
    assert cleaned[1]["category"] == "无瑕疵"
    assert cleaned[1]["confidence"] == 1.0
    assert cleaned[1]["need_human"] is False


def test_vision_context_has_plan_and_sla() -> None:
    """上下文块含定级 + 方案{退/换/补/修} + 时效 + 转人工标记。"""
    block = chat_service.build_vision_context(
        [
            {
                "category": "破洞",
                "confidence": 0.85,
                "desc": "袖口破洞",
                "need_human": False,
            },
            {
                "category": "无瑕疵",
                "confidence": 0.55,
                "desc": "待确认",
                "need_human": True,
            },
        ]
    )
    assert "破洞" in block and "换货" in block and "48 小时" in block
    assert "转人工复核" in block


def test_build_messages_injects_vision() -> None:
    """检测块插在资料与问题之间，无块时不出现标题行。"""
    refs = [{"title": "退换政策", "content": "7 天无理由"}]
    with_vision = chat_service.build_messages("能退吗", refs, "图1：破洞")
    assert "【图像检测】" in with_vision[1]["content"]
    plain = chat_service.build_messages("能退吗", refs)
    assert "【图像检测】" not in plain[1]["content"]


# ---------------- 语音 ----------------


async def test_transcribe_empty_rejects() -> None:
    """空语音 1001 中文提示。"""
    with pytest.raises(BusinessError) as exc:
        await speech_service.transcribe(filename="v.webm", content_type="audio/webm", size=0)
    assert exc.value.code == ErrorCode.PARAM_INVALID


async def test_transcribe_degraded_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """ASR 关闭走规则转写：售后文件名高置信，通用低置信待确认。"""
    monkeypatch.setattr(settings, "ASR_ENABLED", False)
    hot = await speech_service.transcribe(
        filename="退货-破洞.webm", content_type="audio/webm", size=100
    )
    assert hot["confidence"] == 0.82
    assert hot["need_confirm"] is False
    cold = await speech_service.transcribe(filename="hi.webm", content_type="audio/webm", size=100)
    assert cold["need_confirm"] is True
    assert cold["degraded"] is True


async def test_transcribe_gateway_verbose_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """网关打桩：verbose_json 按 no_speech_prob 折置信度，不降级。"""

    async def _fake(
        url: str,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        assert url.endswith("/audio/transcriptions")
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "text": "这件要退货",
                "segments": [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.3}],
            },
            request=request,
        )

    monkeypatch.setattr(speech_service, "_post_audio", _fake)
    out = await speech_service.transcribe(
        filename="v.webm", content_type="audio/webm", size=100, audio=b"fake-audio"
    )
    assert out["text"] == "这件要退货"
    assert out["confidence"] == 0.8
    assert out["need_confirm"] is False
    assert out["degraded"] is False


async def test_transcribe_gateway_plain_json_defaults_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网关只回 text → 置信度默认 0.7 交阈值判定。"""

    async def _fake(
        url: str,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"text": "你好"}, request=request)

    monkeypatch.setattr(speech_service, "_post_audio", _fake)
    out = await speech_service.transcribe(
        filename="v.webm", content_type="audio/webm", size=100, audio=b"fake-audio"
    )
    assert out["confidence"] == 0.7 and out["degraded"] is False


async def test_transcribe_gateway_error_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """网关 500 → 文件名 stub（不断流）。"""

    async def _fake(
        url: str,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(500, text="bad gateway", request=request)

    monkeypatch.setattr(speech_service, "_post_audio", _fake)
    out = await speech_service.transcribe(
        filename="退货.webm", content_type="audio/webm", size=100, audio=b"fake-audio"
    )
    assert out["degraded"] is True


def test_synthesize_voice_guard() -> None:
    """空文本/非法音色 1001；正常回默认晓晓。"""
    with pytest.raises(BusinessError):
        speech_service.synthesize(text="  ")
    with pytest.raises(BusinessError):
        speech_service.synthesize(text="你好", voice="不存在的音色")
    out = speech_service.synthesize(text="你好")
    assert out["voice"] == settings.TTS_VOICE


# ---------------- 对象存储 ----------------


def test_media_roundtrip_isolated(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同租户可回读；跨租户同 404；file_id 非法字符直接拒。"""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    saved = media_store.save_upload(
        tenant="demo-tenant",
        kind="image",
        session_id="s1",
        filename="破洞.jpg",
        raw=b"fake-bytes",
    )
    assert media_store.resolve_path(tenant="demo-tenant", file_id=saved["file_id"]) is not None
    assert media_store.resolve_path(tenant="other-tenant", file_id=saved["file_id"]) is None
    assert media_store.resolve_path(tenant="demo-tenant", file_id="../evil") is None


def test_media_s3_backend_fails_loud(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """s3 后端写对象失败（客户端不可用）：显式报 5001，不静默落本地盘（防两处副本分叉）。"""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MEDIA_BACKEND", "s3")
    monkeypatch.setattr(media_store, "_s3_off", True)  # 模拟客户端构造失败（sticky 降级）
    assert media_store.status()["degraded"] is True
    with pytest.raises(BusinessError) as exc:
        media_store.save_upload(
            tenant="demo-tenant", kind="image", session_id="s2", filename="a.png", raw=b"x"
        )
    assert exc.value.code == ErrorCode.UPSTREAM_FAILED
    assert not list(tmp_path.rglob("*.*"))  # 未静默落盘
