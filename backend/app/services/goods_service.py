"""商品服务（/goods：SPU-SKU 矩阵、上下架、改价恒进审批）

链路：endpoints/goods → 本模块 → products/skus 表 + approval_service（改价落审批）。
红线（数据模型文档 §2.1 approvals）：改价**不直接生效**，一律生成审批单，
      由 approval_service.decide 批准后才写 SKU 售价。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Approval, Product, Sku
from app.services import approval_service

GOODS_STATUSES = ("draft", "on", "off")
GOODS_STATUS_LABELS = {"draft": "草稿", "on": "在售", "off": "已下架"}
SKU_STATUS_LABELS = {"on": "在售", "off": "停售"}


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def sku_code(product_spu_no: str, color: str, size: str) -> str:
    """展示用 SKU 编码：SPU-颜色-尺码（口径全站唯一，前端不再自拼）。"""
    return "-".join(part for part in (product_spu_no, color, size) if part)


def sku_to_dict(sku: Sku, product_spu_no: str) -> dict[str, Any]:
    return {
        "id": sku.id,
        "sku_code": sku_code(product_spu_no, sku.color, sku.size),
        "color": sku.color,
        "size": sku.size,
        "barcode": sku.barcode,
        "list_price": sku.list_price,
        "sale_price": sku.sale_price,
        "status": sku.status,
        "status_label": SKU_STATUS_LABELS.get(sku.status, sku.status),
    }


def to_dict(product: Product, skus: list[Sku]) -> dict[str, Any]:
    return {
        "id": product.id,
        "spu_no": product.spu_no,
        "name": product.name,
        "category": product.category,
        "status": product.status,
        "status_label": GOODS_STATUS_LABELS.get(product.status, product.status),
        "images": _parse_json(product.images, []),
        "attrs": _parse_json(product.attrs, {}),
        "created_at": product.created_at.isoformat(sep=" ", timespec="seconds"),
        "skus": [sku_to_dict(s, product.spu_no) for s in skus],
    }


async def _get_product(db: AsyncSession, tenant: str, product_id: str) -> Product:
    row = (
        await db.execute(select(Product).where(Product.tenant == tenant, Product.id == product_id))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "商品不存在或无权访问", 404)
    return row


async def _get_sku(db: AsyncSession, tenant: str, sku_id: str) -> tuple[Sku, Product]:
    sku = (
        await db.execute(select(Sku).where(Sku.tenant == tenant, Sku.id == sku_id))
    ).scalar_one_or_none()
    if sku is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "SKU 不存在或无权访问", 404)
    product = await _get_product(db, tenant, sku.product_id)
    return sku, product


async def list_goods(
    db: AsyncSession,
    *,
    tenant: str,
    keyword: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """SPU 分页 + 一次取回全部 SKU（避免 N+1），供 /goods 矩阵展开。"""
    if status and status not in GOODS_STATUSES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"商品状态非法：{status}（可选 {'/'.join(GOODS_STATUSES)}）",
        )
    stmt = select(Product).where(Product.tenant == tenant)
    if status:
        stmt = stmt.where(Product.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Product.name.like(like), Product.spu_no.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Product.created_at.desc(), Product.spu_no)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    grouped: dict[str, list[Sku]] = {}
    if rows:
        sku_rows = (
            await db.execute(
                select(Sku)
                .where(Sku.product_id.in_([r.id for r in rows]))
                .order_by(Sku.color, Sku.size)
            )
        ).scalars()
        for sku in sku_rows:
            grouped.setdefault(sku.product_id, []).append(sku)
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [to_dict(r, grouped.get(r.id, [])) for r in rows],
    }


async def submit_price_change(
    db: AsyncSession,
    *,
    tenant: str,
    sku_id: str,
    new_price: int,
    reason: str,
    applicant: str,
) -> Approval:
    """改价申请：只落审批单，SKU 价格保持原值（红线：改价恒进审批）。"""
    if new_price <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "新售价必须是大于 0 的整数（单位：分）")
    if not reason.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写改价原因（审批需要）")
    sku, product = await _get_sku(db, tenant, sku_id)
    approval = await approval_service.create(
        db,
        tenant=tenant,
        action="sku.price_change",
        target=sku.id,
        args={
            "sku_id": sku.id,
            "old_price": sku.sale_price,
            "new_price": new_price,
        },
        reason=reason.strip(),
        applicant=applicant,
    )
    approval.target = f"{product.spu_no} {product.name}｜{sku.color}/{sku.size}"
    await db.commit()
    return approval


async def apply_price_change(
    db: AsyncSession, *, tenant: str, args: dict[str, Any], actor: str
) -> None:
    """审批通过后的生效动作（由 approval_service._apply 调用，不单独暴露端点）。"""
    sku_id = str(args.get("sku_id", ""))
    new_price = args.get("new_price")
    if not sku_id or not isinstance(new_price, int) or new_price <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "审批参数缺失：需要 sku_id 与正整数 new_price")
    sku, _ = await _get_sku(db, tenant, sku_id)
    sku.sale_price = new_price


async def update_sku(
    db: AsyncSession,
    *,
    tenant: str,
    sku_id: str,
    barcode: str | None = None,
    status: str | None = None,
) -> Sku:
    """行内编辑条码/上下架。

    注意：**不含价格字段**——售价变更必须走 submit_price_change（审批红线）。
    """
    sku, _ = await _get_sku(db, tenant, sku_id)
    if status is not None:
        if status not in SKU_STATUS_LABELS:
            raise BusinessError(ErrorCode.PARAM_INVALID, f"SKU 状态非法：{status}（可选 on/off）")
        sku.status = status
    if barcode is not None:
        sku.barcode = barcode.strip()
    await db.commit()
    return sku


async def set_goods_status(
    db: AsyncSession, *, tenant: str, product_id: str, status: str
) -> Product:
    """SPU 上下架（下架需前端二次确认，后端只校验状态合法性）。"""
    if status not in GOODS_STATUSES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"商品状态非法：{status}（可选 {'/'.join(GOODS_STATUSES)}）"
        )
    product = await _get_product(db, tenant, product_id)
    product.status = status
    await db.commit()
    return product
