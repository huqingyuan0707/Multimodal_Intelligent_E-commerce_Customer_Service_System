"""审批中心单测（驳回必填/超期升级/政策引用/详情，对齐 API 规范 §4.5 + 页面设计 §3.4）

覆盖：驳回空理由 1001 / 超期标记与只看超期筛选 / 政策引用命中与空回退 / 跨租户详情 404。
运行（backend/ 目录）：pytest tests/test_approvals.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import Approval, KbDoc
from app.db.session import get_engine, init_models
from app.services import approval_service

TENANT = settings.SEED_TENANT


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（与 test_b2b_services.py 同口径，不灌演示数据，审批单现建）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'appr.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def _pending(db: AsyncSession, action: str = "order.refund") -> Approval:
    row = await approval_service.create(
        db,
        tenant=TENANT,
        action=action,
        target="订单 T1",
        args={"amount": 12900},
        reason="冒烟申请",
        applicant="buyer",
    )
    await db.commit()
    return row


async def test_reject_requires_reason(db: AsyncSession) -> None:
    """驳回理由必填：空理由 1001，有理由才落 rejected 并留痕。"""
    row = await _pending(db)
    with pytest.raises(BusinessError) as exc:
        await approval_service.decide(
            db, tenant=TENANT, approval_id=row.id, approve=False, approver="boss", reason="  "
        )
    assert exc.value.code == ErrorCode.PARAM_INVALID
    decided = await approval_service.decide(
        db, tenant=TENANT, approval_id=row.id, approve=False, approver="boss", reason="证据不足"
    )
    assert decided.status == "rejected"
    assert "证据不足" in decided.reason


async def test_overdue_flag_and_filter(db: AsyncSession) -> None:
    """超期升级：等待超 SLA 即标 overdue，只看超期筛得出、筛得准。"""
    fresh = await _pending(db)
    assert approval_service.to_dict(fresh)["overdue"] is False
    old = await _pending(db)
    old.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        hours=settings.APPROVAL_SLA_HOURS + 6
    )
    await db.commit()
    assert approval_service.to_dict(old)["overdue"] is True
    assert approval_service.to_dict(old)["waiting_hours"] >= settings.APPROVAL_SLA_HOURS
    page = await approval_service.list_page(db, tenant=TENANT, overdue_only=True)
    ids = [item["id"] for item in page["items"]]
    assert old.id in ids and fresh.id not in ids


async def test_overdue_cleared_after_decision(db: AsyncSession) -> None:
    """已处理单不标超期（超期只针对待办）。"""
    old = await _pending(db)
    old.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        hours=settings.APPROVAL_SLA_HOURS + 6
    )
    await db.commit()
    decided = await approval_service.decide(
        db, tenant=TENANT, approval_id=old.id, approve=False, approver="boss", reason="超时关闭"
    )
    assert approval_service.to_dict(decided)["overdue"] is False


async def test_policy_refs_hit_and_miss(db: AsyncSession) -> None:
    """政策引用：同租户标题命中 TopN，未知类型/无命中回空数组。"""
    db.add(KbDoc(tenant=TENANT, title="七天无理由退货", content="正文"))
    await db.commit()
    refs = await approval_service.policy_refs(db, tenant=TENANT, action="order.refund")
    assert any(r["title"] == "七天无理由退货" for r in refs)
    assert await approval_service.policy_refs(db, tenant=TENANT, action="nope.unknown") == []
    assert await approval_service.policy_refs(db, tenant="other", action="order.refund") == []


async def test_detail_cross_tenant_404(db: AsyncSession) -> None:
    """详情越权与不存在同口径 404，不泄漏他租户数据。"""
    row = await _pending(db)
    with pytest.raises(BusinessError) as exc:
        await approval_service.get_or_raise(db, "other", row.id)
    assert exc.value.code == ErrorCode.NOT_FOUND
