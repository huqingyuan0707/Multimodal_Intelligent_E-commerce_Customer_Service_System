"""记忆单测（跨会话短期 24h + 长期偏好 + 快照 + 遗忘，对齐 FR-4/FR-1.4 + 数据模型 §4）

覆盖：事实抽取规则/范围/PII 守门 → 记录召回往返 + TTL 滑动 → 显式授权落长期 →
快照命中/失效/脏形回退 → 块顺序与预算钉死 → 删会话清扫/一键遗忘 → assemble 接线。
运行（backend/ 目录）：pytest tests/test_memory.py
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core import cache
from app.core.pii import contains_pii
from app.db import session as session_mod
from app.db.session import get_engine, init_models
from app.services import context_service, memory_service, session_service

TENANT = "mem-t1"
USER = "mem-u1"


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例前后清记忆键（cache.reset 只清粘性与内存，不碰真 Redis）。"""
    cache.reset()
    yield
    cache.reset()


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（含 user_preferences 新表，init_models 全量建表）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'mem.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


def test_extract_facts_keyword_and_pair() -> None:
    """关键词 + 身高体重双填启发式（纯函数）。"""
    facts = memory_service.extract_facts("我身高180体重65，喜欢宽松，预算500元，穿M码，记住")
    assert facts == {
        "height_cm": "180cm",
        "weight_kg": "65kg",
        "fit": "宽松",
        "budget_cny": "500元",
        "size": "M",
    }
    assert memory_service.extract_facts("180，65") == {"height_cm": "180cm", "weight_kg": "65kg"}
    assert memory_service.extract_facts("胸围88腰围66") == {"bust_cm": "88cm", "waist_cm": "66cm"}
    assert memory_service.extract_facts("130斤") == {}
    assert memory_service.extract_facts("我体重130斤") == {"weight_kg": "65kg"}


def test_extract_facts_rejects_ranges_and_noise() -> None:
    """范围外数字/无关键词不认（防把单号金额当事实）。"""
    assert memory_service.extract_facts("身高99") == {}
    assert memory_service.extract_facts("身高300") == {}
    assert memory_service.extract_facts("订单2024091400821") == {}
    assert memory_service.extract_facts("M-L均可") == {}
    assert memory_service.is_explicit_preference("记住我穿M码") is True
    assert memory_service.is_explicit_preference("我身高180") is False


def test_contains_pii_gates_values() -> None:
    """PII 守门：手机/身份证/邮箱命中，普通文本放行。"""
    assert contains_pii("13812345678") is True
    assert contains_pii("110101199001011234") is True
    assert contains_pii("a@b.com") is True
    assert contains_pii("我身高180") is False
    assert contains_pii("") is False


async def test_record_recall_roundtrip_and_ttl(db: AsyncSession) -> None:
    """记录→召回往返；TTL 按 SHORT_TTL 滑动续期（24h）。"""
    out = await memory_service.record_turn(
        db, tenant=TENANT, username=USER, query="我身高180体重65"
    )
    assert out == {"short": 2, "prefs": 0}
    assert await memory_service.recall_short(TENANT, USER) == {
        "height_cm": "180cm",
        "weight_kg": "65kg",
    }
    assert "180cm" in memory_service.render_recent({"height_cm": "180cm"})
    assert memory_service.render_recent({}) == ""
    expire, _ = cache._mem[memory_service.user_key(TENANT, USER)]
    assert abs(expire - (time.time() + settings.MEMORY_SHORT_TTL)) < 120


async def test_prefs_only_on_explicit_and_switch(db: AsyncSession) -> None:
    """长期偏好：无"记住"不落 PG；显式才落；总开关关闭也不落。"""
    await memory_service.record_turn(db, tenant=TENANT, username=USER, query="喜欢宽松")
    assert await memory_service.recall_prefs(db, tenant=TENANT, username=USER) == {}
    out = await memory_service.record_turn(
        db, tenant=TENANT, username=USER, query="记住，以后都穿M码"
    )
    assert out["prefs"] == 1
    prefs = await memory_service.recall_prefs(db, tenant=TENANT, username=USER)
    assert prefs == {"size": "M"}
    assert "M" in memory_service.render_prefs(prefs)


async def test_snapshot_hit_stale_and_malformed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """快照：命中直返；updated_at 变即失效；脏形回 None；开关关闭长期召回空。"""
    row = await session_service.create_session(db, tenant=TENANT, username=USER, title="快照")
    await db.commit()
    updated = row.updated_at.isoformat()
    assert await memory_service.snapshot_read(TENANT, USER, row.id, updated) is None
    await memory_service.snapshot_write(
        TENANT, USER, row.id, updated_at=updated, block="B", stats={"rounds": 1}, summary="S"
    )
    hit = await memory_service.snapshot_read(TENANT, USER, row.id, updated)
    assert hit is not None and hit["block"] == "B"
    assert await memory_service.snapshot_read(TENANT, USER, row.id, "2000-01-01") is None
    await cache.set_json(memory_service.thread_key(TENANT, USER, row.id), {"nope": 1}, 60)
    assert await memory_service.snapshot_read(TENANT, USER, row.id, updated) is None
    monkeypatch.setattr(settings, "MEMORY_LONG_ENABLED", False)
    assert await memory_service.recall_prefs(db, tenant=TENANT, username=USER) == {}


async def test_block_order_and_budget_pins_memory() -> None:
    """块顺序摘要→偏好→近况→窗口；超预算先丢窗口行，记忆钉死。"""
    from app.db.models import Message

    rows = [
        Message(
            session_id="s", tenant="t", role="user" if i % 2 == 0 else "agent", content=f"消息{i}"
        )
        for i in range(6)
    ]
    block, stats = context_service.build_history_block(
        rows,
        "摘要",
        budget=40,
        extra_blocks=("【长期偏好】\n版型偏好：宽松", "【用户近况】\n身高：180cm"),
    )
    assert block.index("【上文摘要】") < block.index("【长期偏好】") < block.index("【用户近况】")
    assert "【长期偏好】" in block and "【用户近况】" in block
    assert stats["dropped"] > 0


async def test_assemble_wires_memory_and_snapshot(db: AsyncSession) -> None:
    """assemble 接线：首轮 PG 建块并写快照，次轮快照命中（snapshot==1）。"""
    row = await session_service.create_session(db, tenant=TENANT, username=USER, title="接线")
    await session_service.save_user_message(
        db, tenant=TENANT, session_id=row.id, content="退货政策", client_msg_id="k1"
    )
    await session_service.save_agent_message(
        db,
        tenant=TENANT,
        session_id=row.id,
        content="7天无理由",
        citations=[],
        guard={},
        faithfulness=1.0,
        trace_id="t",
        client_msg_id="k1",
    )
    await db.commit()
    await memory_service.record_turn(db, tenant=TENANT, username=USER, query="我身高180")
    block1, stats1, _ = await context_service.assemble(db, session=row)
    assert "【用户近况】" in block1 and stats1["memory_recent"] == 1 and stats1["snapshot"] == 0
    block2, stats2, _ = await context_service.assemble(db, session=row)
    assert block2 == block1 and stats2["snapshot"] == 1


async def test_forget_thread_and_user(db: AsyncSession) -> None:
    """遗忘：删会话清扫线程快照；一键遗忘清偏好+近况+全线程扫，审计留痕。"""
    row = await session_service.create_session(db, tenant=TENANT, username=USER, title="遗忘")
    await db.commit()
    await memory_service.record_turn(db, tenant=TENANT, username=USER, query="记住，我身高180")
    await memory_service.snapshot_write(
        TENANT, USER, row.id, updated_at="x", block="B", stats={}, summary=""
    )
    await session_service.delete_session(db, tenant=TENANT, username=USER, session_id=row.id)
    assert await memory_service.snapshot_read(TENANT, USER, row.id, "x") is None
    assert await memory_service.recall_short(TENANT, USER) == {"height_cm": "180cm"}
    out = await memory_service.forget_user(db, tenant=TENANT, username=USER)
    assert out == {"prefs": 1, "threads": 0}
    assert await memory_service.recall_short(TENANT, USER) == {}
    assert await memory_service.recall_prefs(db, tenant=TENANT, username=USER) == {}
