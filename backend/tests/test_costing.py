"""成本折算测试（单价折算 + 定价来源 + 消息行回填，对齐 FRD §1 降本增效）

链路：costing.price_llm_turn 纯折算 → chat_turn_store._record_cost_and_audit
      双写（CostRecord + messages.cost_cents）→ 看板/评估同口径。
运行（backend/ 目录）：pytest tests/test_costing.py
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.core.user_context import CurrentUser
from app.db import session as session_mod
from app.db.models import CostRecord
from app.db.models_foundation import Message
from app.db.session import init_models
from app.services import chat_turn_store, costing

USER = CurrentUser(username="buyer1", tenant="demo-tenant", roles=[])


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """独立临时库（create_all 建表，含新 pricing_source 列）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cost.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert session_mod._SessionFactory is not None
    async with session_mod._SessionFactory() as session:
        yield session
        await session.rollback()


def test_price_math() -> None:
    """折算数学：15 万 tokens × 0.002 元/千 × 100 = 30 分；零负归零。"""
    assert costing.price_llm_turn(100000, 50000) == 30
    assert costing.price_llm_turn(0, 0) == 0
    assert costing.price_llm_turn(-5, -5) == 0


def test_human_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    """人工对照：150 分 ≈ 基线 1500 分的 10%；基线未配回 None 不编数。"""
    assert costing.vs_human_ratio(150) == 10.0
    monkeypatch.setattr(settings, "HUMAN_COST_PER_TICKET_CENTS", 0)
    assert costing.vs_human_ratio(150) is None


async def test_record_usage_priced(db) -> None:  # type: ignore[no-untyped-def]
    """上游双双有数 → 实数单：CostRecord 30 分 source=usage，消息行同步回填。"""
    db.add(Message(id="m1", session_id="s1", tenant=USER.tenant, role="agent", content="答"))
    await db.flush()
    result = {
        "answer": "答",
        "model": "qwen2.5:0.5b",
        "trace_id": "t1",
        "faithfulness": 1.0,
        "message_id": "m1",
        "usage": {"prompt_tokens": 100000, "completion_tokens": 50000},
    }
    await chat_turn_store._record_cost_and_audit(
        db, user=USER, session_id="s1", result=result, query="问"
    )
    row = (await db.execute(select(CostRecord).where(CostRecord.session_id == "s1"))).scalar_one()
    assert (row.cost_cents, row.pricing_source) == (30, "usage")
    assert row.prompt_tokens == 100000 and row.completion_tokens == 50000
    msg = (await db.execute(select(Message).where(Message.id == "m1"))).scalar_one()
    assert msg.cost_cents == 30


async def test_record_estimate_source(db) -> None:  # type: ignore[no-untyped-def]
    """无上游 usage → 估算单：source=estimate，费用来自 estimate_tokens（>0 不恒零）。"""
    result = {"answer": "答复内容", "model": "template", "trace_id": "t2", "faithfulness": 0.0}
    await chat_turn_store._record_cost_and_audit(
        db, user=USER, session_id="s2", result=result, query="问价"
    )
    row = (await db.execute(select(CostRecord).where(CostRecord.session_id == "s2"))).scalar_one()
    assert row.pricing_source == "estimate" and row.cost_cents >= 0
    total = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 0  # 无 message_id 不碰消息表
