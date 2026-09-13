"""RAG 生成段单测：本地模型作答 / 降级不 500 / 引用忠实度（对齐 RAG 规范 §4 + ADR-0001）

覆盖：有据走模型（model=qwen2.5、degraded=false）→ 模型挂了降级片段摘要（degraded=true、仍 200 结构）
      → 无据仍抛 NoEvidenceError(2001) → 越界引用扣忠实度。打桩 _post，不依赖真实 Ollama。
运行（backend/ 目录）：pytest tests/test_chat_llm.py
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.user_context import CurrentUser, set_current_user
from app.services import chat_service, llm_service


@pytest.fixture
def demo_user() -> Iterator[None]:
    """写入 ContextVar 租户（answer 的可见范围口径：Token 推导，不信请求体）。"""
    set_current_user(CurrentUser(username="tester", tenant="demo-tenant", roles=["cs"]))
    yield
    set_current_user(None)


def _patch_post(monkeypatch: pytest.MonkeyPatch, resp: httpx.Response | Exception) -> None:
    async def _fake(url: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(llm_service, "_post", _fake)


def _chat_resp(content: str) -> httpx.Response:
    request = httpx.Request("POST", "http://test/chat/completions")
    body = {"model": "qwen2.5:0.5b", "choices": [{"message": {"content": content}}]}
    return httpx.Response(200, json=body, request=request)


def test_build_messages_numbers_refs_and_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_service.settings, "LLM_REF_CHARS", 10)
    refs = [
        {"title": "退货政策", "content": "长" * 50},
        {"title": "发货时效", "content": "短内容"},
    ]
    messages = chat_service.build_messages("怎么退货", refs)
    assert messages[0]["role"] == "system"
    user_part = messages[1]["content"]
    assert "[1]《退货政策》" in user_part and "[2]《发货时效》" in user_part
    assert ("长" * 11) not in user_part  # 单条按 LLM_REF_CHARS 截断


async def test_answer_uses_local_model(monkeypatch: pytest.MonkeyPatch, demo_user: None) -> None:
    _patch_post(monkeypatch, _chat_resp("支持 7 天无理由退货 [1]。"))
    result = await chat_service.answer("退货政策是什么")
    assert result["degraded"] is False
    assert result["guard"] == {"pass": True, "degraded": False}
    assert result["model"] == "qwen2.5:0.5b"
    assert result["faithfulness"] == 1.0
    assert result["trace_id"]


async def test_answer_degrades_never_raises(
    monkeypatch: pytest.MonkeyPatch, demo_user: None
) -> None:
    """模型不可达 → 片段摘要降级，200 结构、绝不 500（AGENTS.md §3 降级红线）。"""
    _patch_post(monkeypatch, httpx.ConnectError("ollama down"))
    result = await chat_service.answer("退货政策是什么")
    assert result["degraded"] is True
    assert result["guard"]["degraded"] is True
    assert result["model"] == "template"
    assert "知识库原文摘要" in str(result["answer"])
    assert result["faithfulness"] == 1.0  # 降级文本引用编号全部在资料范围内


async def test_answer_hallucinated_citation_lowers_faithfulness(
    monkeypatch: pytest.MonkeyPatch, demo_user: None
) -> None:
    _patch_post(monkeypatch, _chat_resp("见 [1]，另有 [9] 政策"))
    result = await chat_service.answer("退货政策是什么")
    assert result["degraded"] is False
    assert result["faithfulness"] < 1.0


async def test_answer_no_evidence_still_rejects(
    monkeypatch: pytest.MonkeyPatch, demo_user: None
) -> None:
    async def _boom(*a: object, **k: object) -> Any:  # 无据时不应触达模型
        raise AssertionError("无据不得请求模型")

    monkeypatch.setattr(llm_service, "_post", _boom)
    with pytest.raises(chat_service.NoEvidenceError):
        await chat_service.answer("今天天气怎么样")
