"""本地大模型网关（Ollama qwen2.5，OpenAI 兼容协议，对齐 ADR-0001 + RAG 规范 §4 生成）

链路：chat_service → complete() → POST {LLM_BASE_URL}/chat/completions → 回复文本。
适配层口径：业务只认 complete()/probe() 两个函数，换云端模型或换机器只改 Settings（
            禁止任何业务文件出现 URL、模型名、密钥字面量）。
降级红线：连不上 / 超时 / 非 2xx / 空回复 → 统一抛 LlmUnavailableError，
          由调用方决定降级策略（片段摘要），本模块绝不把上游异常冒泡成 500。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.core.observability import record


class LlmUnavailableError(Exception):
    """模型不可用（未启用 / 网络失败 / 非 2xx / 响应格式异常 / 空内容）。"""


@dataclass(frozen=True)
class LlmReply:
    """一次补全的结果（latency_ms 与 usage 供成本核算与看板）。"""

    text: str
    model: str
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)


def _chat_url() -> str:
    return settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.LLM_API_KEY.get_secret_value()}"}


async def _post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    """唯一的 HTTP POST 出口（测试在此打桩）。

    trust_env=False：本机 Ollama 走 127.0.0.1，若被系统代理环境变量劫持会直接连不上。
    """
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS, trust_env=False) as client:
        return await client.post(url, json=payload, headers=headers)


async def _get(url: str, headers: dict[str, str]) -> httpx.Response:
    """唯一的 HTTP GET 出口（probe 用，测试在此打桩）。"""
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        return await client.get(url, headers=headers)


def _extract_text(body: dict[str, Any]) -> tuple[str, str, dict[str, int]]:
    """解析 OpenAI 兼容响应；结构异常或内容为空一律视为模型不可用。"""
    try:
        choices = body["choices"]
        raw = choices[0]["message"]["content"] if choices else ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmUnavailableError("模型响应结构异常，缺少 choices[].message.content") from exc
    text = str(raw).strip()
    if not text:
        raise LlmUnavailableError("模型返回空内容，按不可用处理")
    usage_raw = body.get("usage") or {}
    usage = {
        key: int(value)
        for key, value in usage_raw.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    model = str(body.get("model") or settings.LLM_MODEL)
    return text, model, usage


async def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LlmReply:
    """单轮补全（非流式）。messages 为 [{role, content}]，由调用方拼好。"""
    if not settings.LLM_ENABLED:
        raise LlmUnavailableError("LLM_ENABLED=false，大模型未启用")
    if not messages:
        raise LlmUnavailableError("messages 为空，不请求模型")
    payload: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        "stream": False,
    }
    started = time.perf_counter()
    try:
        resp = await _post(_chat_url(), payload, _headers())
    except (httpx.HTTPError, OSError) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        record("llm", {"model": settings.LLM_MODEL, "ok": False, "latency_ms": latency_ms})
        raise LlmUnavailableError(f"模型服务不可达：{exc.__class__.__name__}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code >= 400:
        record("llm", {"model": settings.LLM_MODEL, "ok": False, "latency_ms": latency_ms})
        raise LlmUnavailableError(f"模型返回 HTTP {resp.status_code}：{resp.text[:120]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise LlmUnavailableError("模型响应非 JSON") from exc
    if not isinstance(body, dict):
        raise LlmUnavailableError("模型响应结构异常（顶层非对象）")
    text, model, usage = _extract_text(body)
    record(
        "llm",
        {
            "model": model,
            "ok": True,
            "latency_ms": latency_ms,
            "total_tokens": usage.get("total_tokens", 0),
        },
    )
    return LlmReply(text=text, model=model, latency_ms=latency_ms, usage=usage)


async def probe() -> dict[str, Any]:
    """可用性巡检（供 /governance/status）：拉模型列表，失败只返回状态、不抛异常。"""
    url = settings.LLM_BASE_URL.rstrip("/") + "/models"
    base = {
        "provider": "ollama",
        "model": settings.LLM_MODEL,
        "base_url": settings.LLM_BASE_URL,
        "enabled": settings.LLM_ENABLED,
    }
    if not settings.LLM_ENABLED:
        return {**base, "available": False, "detail": "LLM_ENABLED=false"}
    try:
        resp = await _get(url, _headers())
    except (httpx.HTTPError, OSError):
        return {
            **base,
            "available": False,
            "detail": "模型服务不可达，回复降级为片段摘要（确认 ollama serve 与模型是否已 pull）",
        }
    if resp.status_code >= 400:
        return {**base, "available": False, "detail": f"模型服务返回 HTTP {resp.status_code}"}
    try:
        body = resp.json()
    except ValueError:
        return {**base, "available": False, "detail": "模型服务响应非 JSON"}
    data = body.get("data") if isinstance(body, dict) else None
    # OpenAI 兼容端点模型名字段是 id（Ollama 原生 /api/tags 才是 name），两者都兜
    models = [
        str(item.get("id") or item.get("name") or "")
        for item in data or []
        if isinstance(item, dict)
    ]
    if models and settings.LLM_MODEL not in " ".join(models):
        return {
            **base,
            "available": True,
            "detail": f"服务在线，但未发现 {settings.LLM_MODEL}（已有 {', '.join(models)}），回复可能降级",
        }
    return {**base, "available": True, "detail": "模型服务在线"}
