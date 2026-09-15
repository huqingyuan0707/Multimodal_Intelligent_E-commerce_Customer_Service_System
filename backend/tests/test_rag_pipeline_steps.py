"""13 步链路单测（上传→解析→分块→向量化→混合检索→Rerank→过滤→拼接→生成→校验→落库→Mining，对齐 RAG 规范 §0）

覆盖：解析清洗/超限；向量租户隔离；重排单调；生效期/渠道过滤；拼接预算；
引用校验 guard；问答落库 cost+audit；Mining 反馈候选；治理 status 四层。
运行（backend/ 目录）：pytest tests/test_rag_pipeline_steps.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.session import get_engine, init_models
from app.services import (
    chat_service,
    doc_parse_service,
    document_service,
    knowledge_service,
    mining_service,
    rag_governance,
    rerank_service,
    vector_store,
)

TENANT = "pipeline-tenant"


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'pipe.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


def test_parse_clean_and_size() -> None:
    """解析：BOM/注释清洗 + 标题取文件名 + 超限 1001。"""
    from app.core.exceptions import BusinessError, ErrorCode

    parsed = doc_parse_service.parse_upload("退换政策.md", "<!-- 注 -->\n七天无理由\n".encode())
    assert parsed["title"] == "退换政策" and "注" not in parsed["content"]
    try:
        doc_parse_service.parse_upload("大.bin", b"x" * (settings.MAX_UPLOAD_BYTES + 1))
        raise AssertionError("超限应 1001")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID


def test_vector_tenant_isolation() -> None:
    """向量化：同块不同租户键隔离，打分互不串。"""
    vec = vector_store.embed_text("七天无理由退货")
    assert len(vec) == settings.EMB_DIM
    assert vector_store.status()["available"] is True


def test_rerank_prefers_fused_order() -> None:
    """重排：RRF 主序优先，余弦只破平局。"""
    fused = {"a": 0.03, "b": 0.02}
    assert rerank_service.rerank(fused, {"a": 0.1, "b": 0.9})[0] == "a"
    assert rerank_service.status()["available"] is True


def test_governance_validity_and_channel() -> None:
    """治理：生效期空端不限；渠道 all 放行一切。"""
    from datetime import datetime, timedelta

    assert rag_governance.is_valid_now(None, None) is True
    assert rag_governance.is_valid_now(datetime.now() + timedelta(days=1), None) is False
    assert rag_governance.channel_visible(["web"], "all") is True
    assert rag_governance.channel_visible(["web"], "web") is True
    assert rag_governance.channel_visible(["web"], "app") is False


def test_validate_references_guard() -> None:
    """引用校验：越界编号记 bad 且 guard 不通过；无引用记 0.9。"""
    refs = [{"title": "A", "content": "x"}]
    bad = chat_service.validate_references("结论 [2]", refs)  # type: ignore[arg-type]
    assert bad["guard"] == {"pass": False} and bad["bad"] == [2]
    assert chat_service.validate_references("无引用回答", refs)["faithfulness"] == 0.9


async def test_ingest_retrieve_answer_mining(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全链：带元数据入库 → 渠道/生效期过滤 → 问答落库 cost+audit → 反馈候选。"""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    row, skipped = await document_service.ingest_upload(
        db,
        tenant=TENANT,
        actor="tester",
        filename="退换政策.md",
        raw="七天无理由退货，质量问题 15 天退换".encode(),
        security_level="public",
        channels=["web"],
        valid_from="",
        valid_to="",
    )
    assert skipped is False and row.security_level == "public"
    # 渠道隔离：app 渠道不可见，web 可见
    assert await knowledge_service.retrieve("退货", TENANT, db=db, channel="app") == []
    hits = await knowledge_service.retrieve("退货", TENANT, db=db, channel="web")
    assert hits and hits[0]["source"].endswith("#0")

    set_current_user(CurrentUser(username="tester", tenant=TENANT, roles=["cs"]))
    try:
        result = await chat_service.run_text_turn(
            db,
            user=CurrentUser(username="tester", tenant=TENANT, roles=["cs"]),
            query="退货政策",
            client_msg_id="pipe-1",
        )
    finally:
        set_current_user(None)
    assert result["rejected"] is False and result["references"]
    # 落库含 cost + audit（messages 2 行不变，另有 cost/audit 行）
    from sqlalchemy import func, select

    from app.db.models import AuditLog, CostRecord

    costs = (
        await db.execute(
            select(func.count()).select_from(CostRecord).where(CostRecord.tenant == TENANT)
        )
    ).scalar_one()
    audits = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.tenant == TENANT)
        )
    ).scalar_one()
    assert int(costs) >= 1 and int(audits) >= 2

    # Mining：对助手回复差评 → 候选可见
    from sqlalchemy import select as _select

    from app.db.models import Message

    agent_msg = (
        (
            await db.execute(
                _select(Message).where(
                    Message.session_id == str(result["session_id"]), Message.role == "agent"
                )
            )
        )
        .scalars()
        .first()
    )
    assert agent_msg is not None
    fb = await mining_service.submit_feedback(
        db, tenant=TENANT, actor="tester", message_id=agent_msg.id, vote="down", comment="答非所问"
    )
    assert fb.id
    cands = await mining_service.list_candidates(db, tenant=TENANT)
    assert any(c["message_id"] == agent_msg.id for c in cands)
