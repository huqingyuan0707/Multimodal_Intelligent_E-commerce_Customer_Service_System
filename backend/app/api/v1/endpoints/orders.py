"""订单端点（/orders 与 /aftersales：列表、详情、打单发货、售后单，对齐 API 规范 §4.7）

链路：前端 OrdersView → 本模块 → order_service → sales_orders/logistics_orders/aftersales 表。
状态机与单号校验在 order_service，端点不写业务分支（分层红线）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])
aftersales_router = APIRouter(prefix="/aftersales", tags=["aftersales"])


class ShipRequest(BaseModel):
    company: str
    tracking_no: str


class AftersaleRequest(BaseModel):
    """售后申请：trace_id 关联会话（红线：售后必须可回放到当时那轮对话）。"""

    order_id: str
    reason: str = ""
    amount: int = 0
    trace_id: str = ""
    evidence: list[str] = []


@router.get("")
async def list_orders(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:read", "order:fulfill")),
    status: str = Query(default="", max_length=20),
    platform: str = Query(default="", max_length=20),
    keyword: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """订单列表（含 allowed_actions，前端据此置灰按钮）。"""
    data = await order_service.list_orders(
        db,
        tenant=user.tenant,
        status=status,
        platform=platform,
        keyword=keyword,
        page=page,
        size=size,
    )
    return ok(data, "获取成功")


@router.get("/{order_id}")
async def order_detail(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:read", "order:fulfill")),
) -> dict[str, Any]:
    """订单详情（含面单与售后单）。"""
    data = await order_service.get_detail(db, tenant=user.tenant, order_id=order_id)
    return ok(data, "获取成功")


@router.post("/{order_id}/ship")
async def ship(
    order_id: str,
    payload: ShipRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:fulfill")),
) -> dict[str, Any]:
    """打单发货：状态机 + 物流单号校验。"""
    data = await order_service.ship(
        db,
        tenant=user.tenant,
        order_id=order_id,
        company=payload.company,
        tracking_no=payload.tracking_no,
    )
    return ok(data, "发货成功，已生成面单")


@aftersales_router.post("")
async def create_aftersale(
    payload: AftersaleRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:fulfill")),
) -> dict[str, Any]:
    """发起售后：退款超阈值自动转审批（返回 need_approval 供前端提示）。"""
    data = await order_service.create_aftersale(
        db,
        tenant=user.tenant,
        order_id=payload.order_id,
        reason=payload.reason,
        amount=payload.amount,
        trace_id=payload.trace_id,
        applicant=user.username,
        evidence=payload.evidence,
    )
    msg = "退款金额超阈值，已转审批（批准后生效）" if data["need_approval"] else "售后单已创建"
    return ok(data, msg)


@aftersales_router.get("")
async def list_aftersales(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:read", "order:fulfill")),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """售后单列表（/logistics 工单页复用此数据）。"""
    rows = await order_service.list_aftersales(db, tenant=user.tenant, limit=limit)
    return ok(order_service.aftersales_to_dicts(rows), "获取成功")
