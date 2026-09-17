"""订单端点（/orders 与 /aftersales：列表、详情、打单发货、签收、售后质检处置，对齐 API 规范 §4.7）

链路：前端 OrdersView/AftersaleView → 本模块 → order_service → sales_orders/logistics_orders/aftersales 表。
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


class DisposeRequest(BaseModel):
    """售后质检处置：二次入库（restocked）/ 报损（scrapped）/ 退供（returned）。

    lines 为可选的 SKU 明细（[{sku_id, qty}]），缺省按订单行快照全量入库；
    warehouse_id 缺省取租户默认仓库（与库存列表口径一致）。
    """

    disposition: str
    warehouse_id: str = ""
    lines: list[dict[str, Any]] | None = None


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


@router.post("/{order_id}/confirm")
async def confirm(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:fulfill")),
) -> dict[str, Any]:
    """签收确认：已发货 → 已完成（FR-10.4 状态机「已发→签收→完成」）。"""
    data = await order_service.confirm(db, tenant=user.tenant, order_id=order_id)
    return ok(data, "签收成功，订单已完成")


@aftersales_router.post("/{aftersale_id}/dispose")
async def dispose(
    aftersale_id: str,
    payload: DisposeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:fulfill")),
) -> dict[str, Any]:
    """售后质检处置：二次入库 / 报损（恒进审批）/ 退供。"""
    data = await order_service.dispose(
        db,
        tenant=user.tenant,
        aftersale_id=aftersale_id,
        disposition=payload.disposition,
        warehouse_id=payload.warehouse_id,
        lines=payload.lines,
        applicant=user.username,
    )
    msg = (
        "报损已转审批（批准后生效）"
        if data["need_approval"]
        else f"处置成功：{data['disposition_label']}"
    )
    return ok(data, msg)


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
    status: str = Query(default="", max_length=20),
    disposition: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """售后单服务端分页列表（前端红线：所有列表页必须服务端分页，默认 20 可切 10/20/50/100）。"""
    data = await order_service.list_aftersales(
        db, tenant=user.tenant, status=status, disposition=disposition, page=page, size=size
    )
    return ok(data, "获取成功")
