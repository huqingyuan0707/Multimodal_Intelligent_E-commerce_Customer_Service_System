"""营销端点（活动/发券/会员，对齐 API 规范 §4.8）

链路：前端 PromoView → 本模块 → promo_service → promos/coupon_grants/members。
端点只做「解析入参 + 调服务 + 组装信封」，业务判断全在服务层（分层红线）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import promo_service

router = APIRouter(prefix="/promos", tags=["promos"])
members_router = APIRouter(prefix="/members", tags=["members"])


class PromoCreateRequest(BaseModel):
    """建活动入参（金额/预算单位：分）。"""

    name: str
    budget: int
    total: int = 0
    per_user: int = 1


class GrantRequest(BaseModel):
    """发券入参（幂等键走请求头 Idempotency-Key，金额核销在订单侧）。"""

    user_ref: str
    order_ref: str = ""


class PointsRequest(BaseModel):
    """积分增减入参（正数为加，负数为扣）。"""

    delta: int


@router.get("")
async def list_promos(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("promo:read", "promo:write")),
) -> dict[str, Any]:
    """活动列表（含预算消耗）。"""
    rows = await promo_service.list_promos(db, tenant=user.tenant)
    return ok([promo_service.promo_to_dict(r) for r in rows], "获取成功")


@router.post("")
async def create_promo(
    payload: PromoCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("promo:write")),
) -> dict[str, Any]:
    """建活动（草稿即 published 可发券，发布流 P2）。"""
    row = await promo_service.create_promo(
        db,
        tenant=user.tenant,
        name=payload.name,
        budget=payload.budget,
        total=payload.total,
        per_user=payload.per_user,
    )
    await db.commit()
    return ok(promo_service.promo_to_dict(row), "活动已创建")


@router.post("/{promo_id}/grant")
async def grant_coupon(
    promo_id: str,
    payload: GrantRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("promo:write")),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
) -> dict[str, Any]:
    """发券：幂等键去重 + 预算原子扣减；超预算 3006；重复提交回放原单据。"""
    result, replayed = await promo_service.grant(
        db,
        tenant=user.tenant,
        promo_id=promo_id,
        user_ref=payload.user_ref,
        idem_key=idempotency_key,
        order_ref=payload.order_ref,
    )
    await db.commit()
    return ok(result, "重复提交已去重" if replayed else "发券成功")


@members_router.get("/{user_ref}")
async def get_member(
    user_ref: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("promo:read", "promo:write")),
) -> dict[str, Any]:
    """会员档案（不存在即建 v0）。"""
    row = await promo_service.get_member(db, tenant=user.tenant, user_ref=user_ref)
    return ok(promo_service.member_to_dict(row), "获取成功")


@members_router.post("/{user_ref}/points")
async def adjust_points(
    user_ref: str,
    payload: PointsRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("promo:write")),
) -> dict[str, Any]:
    """积分增减（扣到 0 封顶，等级重算）。"""
    row = await promo_service.adjust_points(
        db, tenant=user.tenant, user_ref=user_ref, delta=payload.delta
    )
    await db.commit()
    return ok(promo_service.member_to_dict(row), "积分已更新")
