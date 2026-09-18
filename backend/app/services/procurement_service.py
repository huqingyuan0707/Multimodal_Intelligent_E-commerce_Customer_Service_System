"""采购协同服务（供应商 + 采购单状态机 + 到货质检，对齐 API 规范 §4.7 采购节 / 页面设计 §3.12）

链路：endpoints/purchase → 本模块 → suppliers / purchase_orders（质检合格再写 inventory + stock_moves）
      → /purchase 页：供应商表 + 采购单流转 + 质检卡。
口径：
- 状态机唯一合法路径 draft→approved→received→stocked；rejected（审批驳回）/ returned（质检不合格）为终态；
- 审批前不动账：只有 qc(pass) 才写库存与流水（同改价/盘点「批准才生效」红线）；
- 采购单行快照（name/color/size）由服务端从 SKU 取，**不接受前端传入的行名**（防伪造）；
- approve/receive/qc 写操作同步记 audit_logs（与业务同事务，只追加不改）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Product, PurchaseOrder, Sku, Warehouse
from app.db.models_biz_ops import PURCHASE_STATUSES
from app.services import admin_service, inventory_service, supplier_service

# 到货日格式：YYYY-MM-DD（空串=未定，供客服承诺交期）
_ETA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 状态中文化（禁止前端硬编码；与 approvals 的 STATUS_LABELS 同款口径）
STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "approved": "已审批",
    "rejected": "已驳回",
    "received": "已到货",
    "stocked": "已入库",
    "returned": "已退供",
}
# 状态 → 可执行动作（前端据此置灰按钮，非法流转后端仍 3005 兜底）
ALLOWED_ACTIONS: dict[str, list[str]] = {
    "draft": ["approve"],
    "approved": ["receive"],
    "received": ["qc"],
    "rejected": [],
    "stocked": [],
    "returned": [],
}
MAX_ITEMS = 50
MAX_QTY = 100000


def _dt_text(value: datetime | None) -> str:
    """时间统一口径：空格秒（与订单/商品/审批一致，禁止裸 isoformat）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_items(text: str) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return [row for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _amount_of(items: list[dict[str, Any]]) -> tuple[int, int]:
    """采购单合计：返回 (总件数, 总金额分)。脏行按 0 跳过，不让一条坏数据炸列表。"""
    qty_total = 0
    amount = 0
    for item in items:
        qty = int(item.get("qty") or 0)
        price = int(item.get("price") or 0)
        qty_total += qty
        amount += qty * price
    return qty_total, amount


def purchase_to_dict(row: PurchaseOrder, *, supplier_name: str = "") -> dict[str, Any]:
    items = _parse_items(row.items)
    qty_total, amount = _amount_of(items)
    return {
        "id": row.id,
        "supplier_id": row.supplier_id or "",
        "supplier_name": supplier_name,
        "warehouse_id": row.warehouse_id,
        "items": items,
        "qty_total": qty_total,
        "amount": amount,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "allowed_actions": ALLOWED_ACTIONS.get(row.status, []),
        "eta": row.eta,
        "qc_result": row.qc_result,
        "qc_note": row.qc_note,
        "created_at": _dt_text(row.created_at),
    }


# ---------------- 采购单 ----------------
async def _order_or_raise(db: AsyncSession, tenant: str, order_id: str) -> PurchaseOrder:
    row = (
        await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.id == order_id, PurchaseOrder.tenant == tenant
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "采购单不存在或无权访问", 404)
    return row


def _check_eta(eta: str) -> str:
    text = eta.strip()
    if text and not _ETA_RE.match(text):
        raise BusinessError(ErrorCode.PARAM_INVALID, "预计到货日格式应为 YYYY-MM-DD")
    return text


async def _build_items(
    db: AsyncSession, *, tenant: str, lines: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """校验采购行并做服务端快照（SKU 必须属本租户，数量/单价上限校验）。"""
    if not lines:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请至少添加一条采购明细")
    if len(lines) > MAX_ITEMS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"单张采购单明细不得超过 {MAX_ITEMS} 条")
    items: list[dict[str, Any]] = []
    for line in lines:
        sku_id = str(line.get("sku_id") or "").strip()
        qty = int(line.get("qty") or 0)
        price = int(line.get("price") or 0)
        if not sku_id:
            raise BusinessError(ErrorCode.PARAM_INVALID, "采购明细缺少 SKU")
        if qty <= 0 or qty > MAX_QTY:
            raise BusinessError(ErrorCode.PARAM_INVALID, "采购数量必须是 1~100000 的正整数")
        if price < 0:
            raise BusinessError(ErrorCode.PARAM_INVALID, "采购单价不能为负")
        sku = (
            await db.execute(select(Sku).where(Sku.id == sku_id, Sku.tenant == tenant))
        ).scalar_one_or_none()
        if sku is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "SKU 不存在或无权访问", 404)
        product = (
            await db.execute(
                select(Product).where(Product.id == sku.product_id, Product.tenant == tenant)
            )
        ).scalar_one_or_none()
        items.append(
            {
                "sku_id": sku.id,
                "name": product.name if product else "",
                "spu_no": product.spu_no if product else "",
                "color": sku.color,
                "size": sku.size,
                "qty": qty,
                "price": price,
            }
        )
    return items


async def list_purchase_orders(
    db: AsyncSession, *, tenant: str, status: str = "", page: int = 1, size: int = 20
) -> dict[str, Any]:
    """采购单分页列表（status 精确筛选，非法值 1001）。"""
    stmt = select(PurchaseOrder).where(PurchaseOrder.tenant == tenant)
    count_stmt = (
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.tenant == tenant)
    )
    if status:
        if status not in PURCHASE_STATUSES:
            raise BusinessError(
                ErrorCode.PARAM_INVALID,
                f"采购单状态非法：{status}（可选 {'/'.join(PURCHASE_STATUSES)}）",
            )
        stmt = stmt.where(PurchaseOrder.status == status)
        count_stmt = count_stmt.where(PurchaseOrder.status == status)
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = list(
        (
            await db.execute(
                stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    names = await supplier_service.supplier_names(db, ids=[row.supplier_id or "" for row in rows])
    return {
        "items": [
            purchase_to_dict(row, supplier_name=names.get(row.supplier_id or "", ""))
            for row in rows
        ],
        "total": total,
        "page": page,
        "size": size,
    }


async def _check_warehouse(db: AsyncSession, *, tenant: str, warehouse_id: str) -> str:
    """收货仓校验（空串=未指定，质检入库时会再拒一次）。"""
    text = warehouse_id.strip()
    if not text:
        return ""
    row = (
        await db.execute(select(Warehouse).where(Warehouse.id == text, Warehouse.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "收货仓不存在或无权访问", 404)
    return text


async def create_purchase_order(
    db: AsyncSession,
    *,
    tenant: str,
    supplier_id: str,
    warehouse_id: str = "",
    lines: list[dict[str, Any]],
    eta: str = "",
    actor: str = "",
) -> PurchaseOrder:
    """建采购单（恒为草稿）；审批前不动账，到货质检合格才入库。"""
    await supplier_service.supplier_or_raise(db, tenant=tenant, supplier_id=supplier_id)
    warehouse = await _check_warehouse(db, tenant=tenant, warehouse_id=warehouse_id)
    items = await _build_items(db, tenant=tenant, lines=lines)
    row = PurchaseOrder(
        tenant=tenant,
        supplier_id=supplier_id,
        warehouse_id=warehouse,
        items=json.dumps(items, ensure_ascii=False),
        status="draft",
        eta=_check_eta(eta),
    )
    db.add(row)
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="purchase.create",
        target=row.id,
        detail={"supplier_id": supplier_id, "qty": _amount_of(items)[0]},
    )
    await db.commit()
    return row


async def approve_purchase_order(
    db: AsyncSession,
    *,
    tenant: str,
    order_id: str,
    approved: bool,
    reason: str = "",
    actor: str = "",
) -> PurchaseOrder:
    """采购审批（仅草稿可审；驳回为终态，驳回理由必填）。"""
    row = await _order_or_raise(db, tenant, order_id)
    if row.status != "draft":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"采购单当前为「{STATUS_LABELS.get(row.status, row.status)}」，仅草稿可审批",
        )
    if not approved and not reason.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "驳回采购单必须填写理由")
    row.status = "approved" if approved else "rejected"
    if not approved:
        row.qc_note = reason.strip()
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="purchase.approve" if approved else "purchase.reject",
        target=row.id,
        detail={"reason": reason.strip()},
    )
    await db.commit()
    return row


async def receive_purchase_order(
    db: AsyncSession, *, tenant: str, order_id: str, eta: str = "", actor: str = ""
) -> PurchaseOrder:
    """到货登记（仅已审批可登记；可回填实际到货日供客服承诺交期）。"""
    row = await _order_or_raise(db, tenant, order_id)
    if row.status != "approved":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"采购单当前为「{STATUS_LABELS.get(row.status, row.status)}」，仅已审批可登记到货",
        )
    if eta.strip():
        row.eta = _check_eta(eta)
    row.status = "received"
    await db.flush()
    await admin_service.record_audit(
        db, tenant=tenant, actor=actor, action="purchase.receive", target=row.id, detail={}
    )
    await db.commit()
    return row


async def _stock_in(db: AsyncSession, *, tenant: str, row: PurchaseOrder, actor: str) -> None:
    """质检合格入库：逐行写 inventory + stock_moves（含收货仓校验）。

    注：`inventory_service.move_stock` 内部自带 commit（行级流水独立落库），
    故入库前已在创建单时校验过 SKU/数量/收货仓；此处只按快照回放，不再二次提交状态。
    """
    if not row.warehouse_id:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请先指定收货仓，合格件才能入库")
    items = _parse_items(row.items)
    for item in items:
        await inventory_service.move_stock(
            db,
            tenant=tenant,
            kind="in",
            warehouse_id=row.warehouse_id,
            sku_id=str(item.get("sku_id") or ""),
            delta=int(item.get("qty") or 0),
            reason=f"采购入库（采购单 {row.id}）",
            actor=actor,
            order_ref=row.id,
        )


async def qc_purchase_order(
    db: AsyncSession,
    *,
    tenant: str,
    order_id: str,
    passed: bool,
    note: str = "",
    actor: str = "",
) -> PurchaseOrder:
    """到货质检（仅已到货可质检）：合格入库并置 stocked，不合格置 returned（退供，不入库）。"""
    row = await _order_or_raise(db, tenant, order_id)
    if row.status != "received":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"采购单当前为「{STATUS_LABELS.get(row.status, row.status)}」，仅已到货可质检",
        )
    if not note.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写质检说明（不合格需注明退供原因）")
    if passed:
        await _stock_in(db, tenant=tenant, row=row, actor=actor)
        row.status = "stocked"
        row.qc_result = "pass"
    else:
        row.status = "returned"
        row.qc_result = "fail"
    row.qc_note = note.strip()
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="purchase.qc",
        target=row.id,
        detail={"result": row.qc_result, "note": row.qc_note},
    )
    await db.commit()
    return row
