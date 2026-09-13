"""营销服务（活动/发券/会员，对齐 FRD FR-10.6/附录 D/F + API 规范 §4.8）

链路：endpoints/promos → 本模块 → promos/coupon_grants/members。
红线：发券预算原子扣减，超预算 3006；idem_key 唯一防重放，重复提交直接回放原结果。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import CouponGrant, Member, Promo


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def promo_to_dict(row: Promo) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "budget": row.budget,
        "granted": row.granted,
        "total": row.total,
        "per_user": row.per_user,
        "status": row.status,
        "remaining": max(0, row.budget - row.granted),
    }


def grant_to_dict(row: CouponGrant) -> dict[str, Any]:
    return {
        "id": row.id,
        "promo_id": row.promo_id,
        "user_ref": row.user_ref,
        "order_ref": row.order_ref,
        "status": row.status,
    }


async def create_promo(
    db: AsyncSession,
    *,
    tenant: str,
    name: str,
    budget: int,
    total: int = 0,
    per_user: int = 1,
) -> Promo:
    """建活动（草稿态；发布流 P2，当前建完即 published 可发券）。"""
    if not name.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "活动名称不能为空")
    if budget <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "预算必须为正数")
    row = Promo(tenant=tenant, name=name.strip(), budget=budget, total=total, per_user=per_user)
    db.add(row)
    await db.flush()
    return row


async def list_promos(db: AsyncSession, *, tenant: str) -> list[Promo]:
    """租户内活动列表（预算消耗一眼可见）。"""
    rows = (await db.execute(select(Promo).where(Promo.tenant == tenant))).scalars().all()
    return list(rows)


async def grant(
    db: AsyncSession,
    *,
    tenant: str,
    promo_id: str,
    user_ref: str,
    idem_key: str,
    order_ref: str = "",
) -> tuple[dict[str, Any], bool]:
    """发券：幂等键去重 + 预算原子扣减。

    返回 (结果, 是否回放)。重复 idem_key 直接回放原单据，不二次扣预算；
    预算耗尽抛 3006。并发下靠唯一约束兜底：后来者回放先行者结果。
    """
    if not idem_key.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "幂等键不能为空")
    existed = (
        await db.execute(
            select(CouponGrant).where(
                CouponGrant.tenant == tenant, CouponGrant.idem_key == idem_key.strip()
            )
        )
    ).scalar_one_or_none()
    if existed is not None:
        return grant_to_dict(existed), True
    promo = (
        await db.execute(select(Promo).where(Promo.id == promo_id, Promo.tenant == tenant))
    ).scalar_one_or_none()
    if promo is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "活动不存在")
    if promo.granted >= promo.budget:
        raise BusinessError(ErrorCode.COUPON_EXHAUSTED, "券预算已用完")
    row = CouponGrant(
        tenant=tenant,
        promo_id=promo.id,
        user_ref=user_ref,
        order_ref=order_ref,
        idem_key=idem_key.strip(),
    )
    promo.granted += 1
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        replay = (
            await db.execute(
                select(CouponGrant).where(
                    CouponGrant.tenant == tenant, CouponGrant.idem_key == idem_key.strip()
                )
            )
        ).scalar_one_or_none()
        if replay is None:
            raise BusinessError(ErrorCode.INTERNAL, "发券冲突，请重试") from exc
        return grant_to_dict(replay), True
    return grant_to_dict(row), False


async def grant_count(db: AsyncSession, *, tenant: str, promo_id: str) -> int:
    """活动已发券数（核销对账用）。"""
    total = (
        await db.execute(
            select(func.count(CouponGrant.id)).where(
                CouponGrant.tenant == tenant, CouponGrant.promo_id == promo_id
            )
        )
    ).scalar_one()
    return int(total)


async def get_member(db: AsyncSession, *, tenant: str, user_ref: str) -> Member:
    """会员不存在即建（v0/0 分起步）。"""
    row = (
        await db.execute(select(Member).where(Member.tenant == tenant, Member.user_ref == user_ref))
    ).scalar_one_or_none()
    if row is None:
        row = Member(tenant=tenant, user_ref=user_ref)
        db.add(row)
        await db.flush()
    return row


def _level_for(points: int) -> str:
    if points >= 5000:
        return "v2"
    if points >= 1000:
        return "v1"
    return "v0"


async def adjust_points(db: AsyncSession, *, tenant: str, user_ref: str, delta: int) -> Member:
    """积分增减（扣到 0 封顶，等级随分重算）。"""
    row = await get_member(db, tenant=tenant, user_ref=user_ref)
    row.points = max(0, row.points + delta)
    row.level = _level_for(row.points)
    await db.flush()
    return row


def member_to_dict(row: Member) -> dict[str, Any]:
    return {"user_ref": row.user_ref, "level": row.level, "points": row.points}
