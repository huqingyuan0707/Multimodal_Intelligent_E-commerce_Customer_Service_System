"""库存端点（/inventory：库存表、出入库/调拨、盘点、补货需求，对齐 API 规范 §4.7）

链路：前端 InventoryView → 本模块 → inventory_service → inventory/stock_moves 表（+ approvals）。
可用量口径由 inventory_service.available_of 唯一提供，端点不重算。
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
from app.services import approval_service, inventory_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


class StockMoveRequest(BaseModel):
    """出入库/调拨入参：数量为正整数，原因必填。"""

    kind: str
    warehouse_id: str
    sku_id: str
    delta: int
    reason: str = ""
    to_warehouse_id: str = ""
    order_ref: str = ""


class StocktakeLine(BaseModel):
    warehouse_id: str
    sku_id: str
    counted: int


class StocktakeRequest(BaseModel):
    lines: list[StocktakeLine]
    reason: str = ""


class ReplenishRequest(BaseModel):
    sku_id: str
    qty: int
    reason: str = ""


@router.get("")
async def stock_table(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:read", "stock:write")),
    warehouse_id: str = Query(default="", max_length=32),
    sku_id: str = Query(default="", max_length=32),
    keyword: str = Query(default="", max_length=64),
    only_warn: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """库存表（SKU × 仓库），含 available 与 warning。keyword 搜 SKU 编码/品名/仓库名。"""
    data = await inventory_service.stock_table(
        db,
        tenant=user.tenant,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        keyword=keyword,
        only_warn=only_warn,
        page=page,
        size=size,
    )
    return ok(data, "获取成功")


@router.get("/warehouses")
async def list_warehouses(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:read", "stock:write")),
) -> dict[str, Any]:
    """仓库下拉数据。"""
    rows = await inventory_service.list_warehouses(db, tenant=user.tenant)
    return ok([{"id": r.id, "name": r.name} for r in rows], "获取成功")


@router.get("/moves")
async def list_moves(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:read", "stock:write")),
    sku_id: str = Query(default="", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """出入库流水（倒序）。"""
    rows = await inventory_service.list_moves(db, tenant=user.tenant, sku_id=sku_id, limit=limit)
    return ok(
        [
            {
                "id": r.id,
                "warehouse_id": r.warehouse_id,
                "sku_id": r.sku_id,
                "kind": r.kind,
                "kind_label": inventory_service.KIND_LABELS.get(r.kind, r.kind),
                "delta": r.delta,
                "reason": r.reason,
                "order_ref": r.order_ref,
                "actor": r.actor,
                "created_at": r.created_at.isoformat(sep=" ", timespec="seconds"),
            }
            for r in rows
        ],
        "获取成功",
    )


@router.post("/moves")
async def create_move(
    payload: StockMoveRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:write")),
) -> dict[str, Any]:
    """入库 / 出库 / 调拨（调拨自动拆两行流水）。"""
    data = await inventory_service.move_stock(
        db,
        tenant=user.tenant,
        kind=payload.kind,
        warehouse_id=payload.warehouse_id,
        sku_id=payload.sku_id,
        delta=payload.delta,
        reason=payload.reason,
        actor=user.username,
        to_warehouse_id=payload.to_warehouse_id,
        order_ref=payload.order_ref,
    )
    return ok(data, f"{data['kind_label']}成功")


@router.post("/stocktake")
async def stocktake(
    payload: StocktakeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:write")),
) -> dict[str, Any]:
    """盘点：差异行进审批，账实一致才免审。"""
    data = await inventory_service.stocktake(
        db,
        tenant=user.tenant,
        lines=[line.model_dump() for line in payload.lines],
        reason=payload.reason,
        actor=user.username,
    )
    msg = (
        f"盘点 {data['checked']} 行，{data['diff_count']} 行有差异，已提交审批（批准后改账）"
        if data["diff_count"]
        else f"盘点 {data['checked']} 行，账实一致"
    )
    return ok(data, msg)


@router.post("/replenish")
async def replenish(
    payload: ReplenishRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("stock:write")),
) -> dict[str, Any]:
    """低于安全线一键生成补货需求（进审批；采购单在 P2 落地）。"""
    approval = await inventory_service.replenish(
        db,
        tenant=user.tenant,
        sku_id=payload.sku_id,
        qty=payload.qty,
        reason=payload.reason,
        applicant=user.username,
    )
    return ok(approval_service.to_dict(approval), "补货需求已提交审批")
