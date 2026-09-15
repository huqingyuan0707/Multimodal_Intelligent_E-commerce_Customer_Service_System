"""商品端点（/goods：SPU-SKU 矩阵、改价审批、条码/上下架，对齐 API 规范 §4.7）

链路：前端 GoodsView → 本模块 → goods_service → products/skus 表（+ approvals）。
端点只做「解析入参 + 调服务 + 组装信封」，业务判断全在服务层（分层红线）。
"""

# temporary: e2e verify ai-diagnose trigger on docs-guard failure

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import approval_service, goods_service

router = APIRouter(prefix="/goods", tags=["goods"])


class PriceChangeRequest(BaseModel):
    """改价申请（金额单位：分）。"""

    new_price: int
    reason: str = ""


class SkuUpdateRequest(BaseModel):
    """SKU 行内编辑：仅条码与上下架，价格不在此列（必须走审批）。"""

    barcode: str | None = None
    status: str | None = None


class GoodsStatusRequest(BaseModel):
    status: str


@router.get("")
async def list_goods(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("goods:read", "goods:write")),
    keyword: str = Query(default="", max_length=60),
    status: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """SPU 列表（含 SKU 矩阵），供 /goods 展开行。"""
    data = await goods_service.list_goods(
        db, tenant=user.tenant, keyword=keyword, status=status, page=page, size=size
    )
    return ok(data, "获取成功")


@router.post("/skus/{sku_id}/price-change")
async def submit_price_change(
    sku_id: str,
    payload: PriceChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("goods:write")),
) -> dict[str, Any]:
    """改价恒进审批：返回审批单，SKU 价格此刻不变。"""
    approval = await goods_service.submit_price_change(
        db,
        tenant=user.tenant,
        sku_id=sku_id,
        new_price=payload.new_price,
        reason=payload.reason,
        applicant=user.username,
    )
    return ok(approval_service.to_dict(approval), "改价已提交审批，通过后自动生效")


@router.put("/skus/{sku_id}")
async def update_sku(
    sku_id: str,
    payload: SkuUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("goods:write")),
) -> dict[str, Any]:
    """行内编辑条码/上下架（不含价格）。"""
    sku = await goods_service.update_sku(
        db, tenant=user.tenant, sku_id=sku_id, barcode=payload.barcode, status=payload.status
    )
    return ok({"id": sku.id, "barcode": sku.barcode, "status": sku.status}, "已保存")


@router.put("/{product_id}/status")
async def set_goods_status(
    product_id: str,
    payload: GoodsStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("goods:write")),
) -> dict[str, Any]:
    """SPU 上下架（前端下架有二次确认）。"""
    product = await goods_service.set_goods_status(
        db, tenant=user.tenant, product_id=product_id, status=payload.status
    )
    label = goods_service.GOODS_STATUS_LABELS.get(product.status, product.status)
    return ok({"id": product.id, "status": product.status}, f"已切换为「{label}」")
