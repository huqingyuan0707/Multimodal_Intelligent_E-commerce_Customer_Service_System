"""本地大模型网关单测（打桩 _post/_get，不依赖真实 Ollama，对齐 ADR-0001 + 测试方案 §2）

覆盖：成功解析 / 未启用 / 空消息 / HTTP≥400 / 非 JSON / 结构异常 / 空内容 / 网络异常 / probe 巡检。
红线口径：任何上游失败都收敛为 LlmUnavailableError，禁止冒泡成 500。
运行（backend/ 目录）：pytest tests/test_llm_service.py
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.config import settings
from app.services import llm_service

_MSGS = [{"role": "user", "content": "退货政策？"}]


def _resp(status: int, body: Any) -> httpx.Response:
    """构造真实 httpx.Response（request 必填，resp.json() 走标准解析）。"""
    request = httpx.Request("POST", "http://test/chat/completions")
    if isinstance(body, (dict, list)):
        return httpx.Response(status, json=body, request=request)
    return httpx.Response(status, text=str(body), request=request)


def _patch_post(monkeypatch: pytest.MonkeyPatch, resp: httpx.Response | Exception) -> None:
    async def _fake(url: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(llm_service, "_post", _fake)


_OK_BODY = {
    "model": "qwen2.5:0.5b",
    "choices": [{"message": {"content": " 支持 7 天无理由退货 [1] "}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


async def test_complete_success_strips_text_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(monkeypatch, _resp(200, _OK_BODY))
    reply = await llm_service.complete(_MSGS)
    assert reply.text == "支持 7 天无理由退货 [1]"
    assert reply.model == "qwen2.5:0.5b"
    assert reply.usage["total_tokens"] == 15
    assert reply.latency_ms >= 0


async def test_complete_disabled_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    with pytest.raises(llm_service.LlmUnavailableError, match="未启用"):
        await llm_service.complete(_MSGS)


async def test_complete_empty_messages_raises() -> None:
    with pytest.raises(llm_service.LlmUnavailableError, match="messages 为空"):
        await llm_service.complete([])


async def test_complete_http_500_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _resp(500, {"error": "model not found"}))
    with pytest.raises(llm_service.LlmUnavailableError, match="HTTP 500"):
        await llm_service.complete(_MSGS)


async def test_complete_non_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _resp(200, "<html>gateway</html>"))
    with pytest.raises(llm_service.LlmUnavailableError, match="非 JSON"):
        await llm_service.complete(_MSGS)


async def test_complete_missing_choices_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _resp(200, {"oops": True}))
    with pytest.raises(llm_service.LlmUnavailableError, match="结构异常"):
        await llm_service.complete(_MSGS)


async def test_complete_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"choices": [{"message": {"content": "   "}}]}
    _patch_post(monkeypatch, _resp(200, body))
    with pytest.raises(llm_service.LlmUnavailableError, match="空内容"):
        await llm_service.complete(_MSGS)


async def test_complete_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, httpx.ConnectError("connection refused"))
    with pytest.raises(llm_service.LlmUnavailableError, match="不可达"):
        await llm_service.complete(_MSGS)


async def test_probe_disabled_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    result = await llm_service.probe()
    assert result["available"] is False
    assert result["model"] == settings.LLM_MODEL


async def test_probe_network_error_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(url: str, headers: dict[str, str]) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm_service, "_get", _fake)
    result = await llm_service.probe()
    assert result["available"] is False
    assert "降级" in str(result["detail"])


async def test_probe_warns_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(url: str, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"name": "llama3:latest"}]})

    monkeypatch.setattr(llm_service, "_get", _fake)
    result = await llm_service.probe()
    assert result["available"] is True
    assert "未发现" in str(result["detail"])
