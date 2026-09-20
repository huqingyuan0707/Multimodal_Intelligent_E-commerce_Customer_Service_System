"""采购端点（供应商 + 采购单状态机 + 到货质检，对齐 API 规范 §4.7 采购节）

链路：前端 /purchase → 本模块（解析入参 + 组装信封）→ supplier_service / procurement_service。
权限：读 `purchase:read|write`、写 `purchase:write`（与商品/库存同款「域角色即权限」口径）。
审批口径：建单即同事务落 `purchase.approve` 审批单进 §4.5 审批中心（本文件无直批端点，
防止绕过审批中心双入口）；批准/驳回走 `POST /approvals/{id}/approve|reject`。
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
from app.services import procurement_service, supplier_service

router = APIRouter(tags=["purchase"])


class SupplierRequest(BaseModel):
    """新建供应商（合格率 0~1，如 0.98 表示 98%）。"""

    name: str
    pay_terms: str = ""
    pass_rate: float = 1.0


class PurchaseLine(BaseModel):
    """采购明细行（行名/SKU 快照由服务端回填，不接受前端传入展示名）。"""

    sku_id: str
    qty: int
    price: int = 0


class PurchaseOrderRequest(BaseModel):
    """建采购单（恒为草稿，审批走审批中心，审批前不动账）。"""

    supplier_id: str
    warehouse_id: str = ""
    items: list[PurchaseLine] = []
    eta: str = ""


class ReceiveRequest(BaseModel):
    """到货登记（可回填实际到货日，供客服承诺交期）。"""

    eta: str = ""


class QcRequest(BaseModel):
    """到货质检：passed=false 即不合格退供（质检说明必填）。"""

    passed: bool = True
    note: str = ""


@router.get("/suppliers")
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:read", "purchase:write")),
    keyword: str = Query(default="", max_length=60),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """供应商分页列表（账期 + 合格率）。"""
    data = await supplier_service.list_suppliers(
        db, tenant=user.tenant, keyword=keyword, page=page, size=size
    )
    return ok(data, "获取成功")


@router.post("/suppliers")
async def create_supplier(
    payload: SupplierRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:write")),
) -> dict[str, Any]:
    """新建供应商。"""
    row = await supplier_service.create_supplier(
        db,
        tenant=user.tenant,
        name=payload.name,
        pay_terms=payload.pay_terms,
        pass_rate=payload.pass_rate,
    )
    return ok(supplier_service.supplier_to_dict(row), "供应商已创建")


@router.get("/purchase")
async def list_purchase_orders(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:read", "purchase:write")),
    status: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """采购单分页列表（含状态中文标签与可执行动作，供前端置灰按钮）。"""
    data = await procurement_service.list_purchase_orders(
        db, tenant=user.tenant, status=status, page=page, size=size
    )
    return ok(data, "获取成功")


@router.post("/purchase")
async def create_purchase_order(
    payload: PurchaseOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:write")),
) -> dict[str, Any]:
    """建采购单（草稿）；同事务落审批单进审批中心，批准后才可到货登记。"""
    row = await procurement_service.create_purchase_order(
        db,
        tenant=user.tenant,
        supplier_id=payload.supplier_id,
        warehouse_id=payload.warehouse_id,
        lines=[line.model_dump() for line in payload.items],
        eta=payload.eta,
        actor=user.username,
    )
    return ok(procurement_service.purchase_to_dict(row), "采购单已创建，审批已转审批中心")


@router.post("/purchase/{order_id}/receive")
async def receive_purchase_order(
    order_id: str,
    payload: ReceiveRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:write")),
) -> dict[str, Any]:
    """到货登记（仅已审批可登记）。"""
    row = await procurement_service.receive_purchase_order(
        db, tenant=user.tenant, order_id=order_id, eta=payload.eta, actor=user.username
    )
    return ok(procurement_service.purchase_to_dict(row), "已登记到货")


@router.post("/purchase/{order_id}/qc")
async def qc_purchase_order(
    order_id: str,
    payload: QcRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("purchase:write")),
) -> dict[str, Any]:
    """到货质检（仅已到货可质检）：合格入库 / 不合格退供。"""
    row = await procurement_service.qc_purchase_order(
        db,
        tenant=user.tenant,
        order_id=order_id,
        passed=payload.passed,
        note=payload.note,
        actor=user.username,
    )
    msg = "质检合格，已入库" if payload.passed else "质检不合格，已标记退供（未入库）"
    return ok(procurement_service.purchase_to_dict(row), msg)
