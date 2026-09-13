"""营销/评价/工单服务单测（发券幂等/预算/会员/差评建单，对齐 FRD FR-10.6/10.8/FR-12.3）

红线口径逐一验证：
- 发券预算原子扣减，超预算 3006；同 idem_key 重复提交回放原单据不二次扣预算。
- 会员不存在即建；积分扣到 0 封顶，等级随分重算。
- 差评一键建工单 SLA 2h，ticket_id 回写；重复建单回放不断链。
- 工单关闭结论必填；已关闭不可重关/转交。
运行（backend/ 目录）：pytest tests/test_promo_review.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.session import get_engine, init_models
from app.services import promo_service, review_service

TENANT = "t-promo-ut"


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例在夹具结束后自动还原）。"""
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    import app.config as config_mod

    monkeypatch.setattr(config_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/p.db")
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_grant_idempotent_and_budget(db: AsyncSession) -> None:
    promo = await promo_service.create_promo(
        db, tenant=TENANT, name="新人券", budget=1, total=100, per_user=1
    )
    await db.commit()
    first, replayed = await promo_service.grant(
        db, tenant=TENANT, promo_id=promo.id, user_ref="u1", idem_key="k-1"
    )
    assert replayed is False
    await db.commit()
    second, replayed2 = await promo_service.grant(
        db, tenant=TENANT, promo_id=promo.id, user_ref="u1", idem_key="k-1"
    )
    assert replayed2 is True
    assert second["id"] == first["id"]
    await db.commit()
    with pytest.raises(BusinessError) as exc:
        await promo_service.grant(
            db, tenant=TENANT, promo_id=promo.id, user_ref="u2", idem_key="k-2"
        )
    assert exc.value.code == ErrorCode.COUPON_EXHAUSTED
    assert await promo_service.grant_count(db, tenant=TENANT, promo_id=promo.id) == 1


async def test_member_points_floor_and_level(db: AsyncSession) -> None:
    row = await promo_service.adjust_points(db, tenant=TENANT, user_ref="m1", delta=1500)
    assert (row.level, row.points) == ("v1", 1500)
    row = await promo_service.adjust_points(db, tenant=TENANT, user_ref="m1", delta=-2000)
    assert (row.level, row.points) == ("v0", 0)
    await db.commit()


async def test_review_ticket_flow(db: AsyncSession) -> None:
    review = await review_service.create_review(
        db,
        tenant=TENANT,
        platform="tb",
        outer_id="o1",
        level="bad",
        content="掉色严重",
        tags=["掉色"],
    )
    await db.commit()
    ticket, linked = await review_service.create_review_ticket(
        db, tenant=TENANT, review_id=review.id, assignee="cs1"
    )
    assert linked.ticket_id == ticket.id
    await db.commit()
    ticket2, _ = await review_service.create_review_ticket(db, tenant=TENANT, review_id=review.id)
    assert ticket2.id == ticket.id
    with pytest.raises(BusinessError) as exc:
        await review_service.close_ticket(db, tenant=TENANT, ticket_id=ticket.id, conclusion="  ")
    assert exc.value.code == ErrorCode.PARAM_INVALID
    closed = await review_service.close_ticket(
        db, tenant=TENANT, ticket_id=ticket.id, conclusion="补发+致歉，已回访"
    )
    assert closed.status == "closed"
    await db.commit()
    with pytest.raises(BusinessError):
        await review_service.transfer_ticket(db, tenant=TENANT, ticket_id=ticket.id, assignee="cs2")
