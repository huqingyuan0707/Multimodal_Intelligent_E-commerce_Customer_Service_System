"""关键词检索单测（纯函数，无 DB/网络，对齐测试方案 §2）

覆盖：打分单调性 / 租户隔离 / 阈值过滤 / 有据组装含引用。
运行（backend/ 目录）：pytest tests/test_knowledge.py
"""

from __future__ import annotations

import pytest

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
async def test_answer_ok_and_reject() -> None:
    set_current_user(CurrentUser(username="demo", tenant="demo-tenant", roles=[]))
    try:
        ok_result = await chat_service.answer("退货政策是什么")
        assert ok_result["references"]
        assert ok_result["faithfulness"] == 1.0
        assert ok_result["trace_id"]
        with pytest.raises(chat_service.NoEvidenceError):
            await chat_service.answer("今天天气怎么样")
    finally:
        set_current_user(None)
