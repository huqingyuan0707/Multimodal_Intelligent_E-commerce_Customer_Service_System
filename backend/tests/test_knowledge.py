"""RAG 检索单测（纯函数 + 降级路径，无 DB/真实模型，对齐测试方案 §2）

覆盖：打分单调性 / 租户隔离 / 有据组装含引用 / 无据拒答 2001。
生成段（模型作答/降级）见 tests/test_chat_llm.py；此处固定 LLM_ENABLED=false 走降级，保证离线可跑。
运行（backend/ 目录）：pytest tests/test_knowledge.py
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.core.user_context import CurrentUser, set_current_user
from app.services import chat_service, knowledge_service


def test_score_hit_higher_than_miss() -> None:
    doc = "支持 7 天无理由退货，质量问题 15 天内退换"
    assert knowledge_service.score("退货政策是什么", doc) > knowledge_service.score(
        "今天天气怎么样", doc
    )


@pytest.mark.asyncio
async def test_retrieve_tenant_isolation() -> None:
    refs = await knowledge_service.retrieve("退货", tenant="other-tenant")
    assert refs == []


@pytest.mark.asyncio
async def test_answer_ok_and_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定关闭大模型：answer 走片段摘要降级（faithfulness 仍 1.0），用例不依赖 Ollama 是否在跑。"""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    set_current_user(CurrentUser(username="demo", tenant="demo-tenant", roles=[]))
    try:
        ok_result = await chat_service.answer("退货政策是什么")
        assert ok_result["references"]
        assert ok_result["faithfulness"] == 1.0
        assert ok_result["trace_id"]
        assert ok_result["degraded"] is True
        with pytest.raises(chat_service.NoEvidenceError):
            await chat_service.answer("今天天气怎么样")
    finally:
        set_current_user(None)
