"""订单服务（/orders：本地镜像列表、打单发货状态机、售后单关联会话 trace）

链路：endpoints/orders → 本模块 → sales_orders/logistics_orders/aftersales 表 + approval_service。
红线：
- 状态机非法流转返回 3005（仅「待发货」可打单发货）。
- 物流单号格式校验（settings.TRACKING_NO_PATTERN），非法 1001。
- 退款金额超阈值恒进审批（3003 号段保留给「未批先退」的拒绝路径，P1 不开放直接退款端点）。
- 售后单必须带 trace_id，供 /orders 抽屉一键跳 workbench 回放。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Aftersale, LogisticsOrder, SalesOrder
from app.services import approval_service

ORDER_STATUSES = ("pending_pay", "paid", "shipped", "completed", "aftersale", "closed")
STATUS_LABELS = {
    "pending_pay": "待付款",
    "paid": "待发货",
    "shipped": "已发货",
    "completed": "已完成",
    "aftersale": "售后中",
    "closed": "已关闭",
}
# 状态机白名单：前端按 allowed_actions 置灰按钮，后端仍二次校验（不信任前端）。
NEXT_ACTIONS: dict[str, tuple[str, ...]] = {
    "pending_pay": (),
    "paid": ("ship",),
    "shipped": ("aftersale",),
    "completed": ("aftersale",),
    "aftersale": (),
    "closed": (),
}
COMPANIES = tuple(settings.LOGISTICS_COMPANIES)  # 快递白名单唯一口径（Settings 可配）


def _items_of(order: SalesOrder) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(order.items or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _evidence_of(row: Aftersale) -> list[str]:
    """证据图 URL 列表（建单时存 JSON 文本，脏数据按空列表处理，链路不断）。"""
    try:
        loaded = json.loads(row.evidence or "[]")
    except json.JSONDecodeError:
        return []
    return [str(u) for u in loaded] if isinstance(loaded, list) else []


def to_dict(order: SalesOrder, logistics: LogisticsOrder | None = None) -> dict[str, Any]:
    items = _items_of(order)
    return {
        "id": order.id,
        "platform": order.platform,
        "outer_id": order.outer_id,
        "status": order.status,
        "status_label": STATUS_LABELS.get(order.status, order.status),
        "total": order.total,
        "item_count": len(items),
        "items": items,
        "trace_id": order.trace_id,
        "allowed_actions": list(NEXT_ACTIONS.get(order.status, ())),
        "company": logistics.company if logistics else "",
        "tracking_no": logistics.tracking_no if logistics else "",
        "logistics_id": (logistics.id or "") if logistics else "",
        "logistics_status": (logistics.status or "") if logistics else "",
        "created_at": order.created_at.isoformat(sep=" ", timespec="seconds"),
    }


async def _get_order(db: AsyncSession, tenant: str, order_id: str) -> SalesOrder:
    row = (
        await db.execute(
            select(SalesOrder).where(SalesOrder.tenant == tenant, SalesOrder.id == order_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.ORDER_NOT_FOUND, "订单不存在或无权访问", 404)
    return row


async def list_orders(
    db: AsyncSession,
    *,
    tenant: str,
    status: str = "",
    platform: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """订单列表（状态/平台/单号筛选 + 面单信息一次带出）。"""
    if status and status not in ORDER_STATUSES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"订单状态非法：{status}（可选 {'/'.join(ORDER_STATUSES)}）",
        )
    stmt = select(SalesOrder).where(SalesOrder.tenant == tenant)
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    if platform:
        stmt = stmt.where(SalesOrder.platform == platform)
    if keyword.strip():
        stmt = stmt.where(SalesOrder.outer_id.like(f"%{keyword.strip()}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(SalesOrder.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    logistics_by_order: dict[str, LogisticsOrder] = {}
    if rows:
        waybills = (
            await db.execute(
                select(LogisticsOrder).where(
                    LogisticsOrder.sales_order_id.in_([r.id for r in rows])
                )
            )
        ).scalars()
        for waybill in waybills:
            logistics_by_order[waybill.sales_order_id] = waybill
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [to_dict(r, logistics_by_order.get(r.id)) for r in rows],
    }


async def get_detail(db: AsyncSession, *, tenant: str, order_id: str) -> dict[str, Any]:
    """订单详情：含面单与售后单（售后抽屉要展示 trace_id 跳转）。"""
    order = await _get_order(db, tenant, order_id)
    waybill = (
        (
            await db.execute(
                select(LogisticsOrder)
                .where(LogisticsOrder.tenant == tenant, LogisticsOrder.sales_order_id == order.id)
                .order_by(LogisticsOrder.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    aftersales = list(
        (
            await db.execute(
                select(Aftersale)
                .where(Aftersale.tenant == tenant, Aftersale.sales_order_id == order.id)
                .order_by(Aftersale.created_at.desc())
            )
        ).scalars()
    )
    data = to_dict(order, waybill)
    data["aftersales"] = [
        {
            "id": row.id,
            "order_id": row.sales_order_id,
            "reason": row.reason,
            "amount": row.amount,
            "evidence": _evidence_of(row),
            "trace_id": row.trace_id,
            "status": row.status,
            "status_label": AFTERSALE_STATUS_LABELS.get(row.status, row.status),
            "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        }
        for row in aftersales
    ]
    return data


async def ship(
    db: AsyncSession,
    *,
    tenant: str,
    order_id: str,
    company: str,
    tracking_no: str,
) -> dict[str, Any]:
    """打单发货：状态机 + 单号校验都过了才写面单并改状态。"""
    order = await _get_order(db, tenant, order_id)
    if order.status != "paid":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"当前状态「{STATUS_LABELS.get(order.status, order.status)}」不可发货，"
            "仅「待发货」订单可打单发货",
        )
    text_company = company.strip()
    if text_company not in COMPANIES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"快递公司非法：{text_company}（可选 {'/'.join(COMPANIES)}）"
        )
    text_no = tracking_no.strip()
    if not re.fullmatch(settings.TRACKING_NO_PATTERN, text_no):
        raise BusinessError(
            ErrorCode.PARAM_INVALID, "物流单号格式不正确（8~24 位字母或数字，无空格）"
        )
    order.status = "shipped"
    db.add(
        LogisticsOrder(
            tenant=tenant,
            sales_order_id=order.id,
            company=text_company,
            tracking_no=text_no,
            status="created",
        )
    )
    await db.commit()
    return to_dict(
        order, LogisticsOrder(company=text_company, tracking_no=text_no, status="created")
    )


async def create_aftersale(
    db: AsyncSession,
    *,
    tenant: str,
    order_id: str,
    reason: str,
    amount: int,
    trace_id: str,
    applicant: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """发起售后：退款金额超阈值自动转审批（账不动，等批准）。"""
    if amount < 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "退款金额不能为负（单位：分）")
    if not reason.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写售后原因")
    order = await _get_order(db, tenant, order_id)
    if "aftersale" not in NEXT_ACTIONS.get(order.status, ()):
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"当前状态「{STATUS_LABELS.get(order.status, order.status)}」不可发起售后",
        )
    need_approval = amount > settings.REFUND_APPROVAL_LIMIT_CENTS
    row = Aftersale(
        tenant=tenant,
        sales_order_id=order.id,
        reason=reason.strip(),
        amount=amount,
        evidence=json.dumps(evidence or [], ensure_ascii=False),
        trace_id=trace_id,
        status="approving" if need_approval else "pending",
    )
    db.add(row)
    await db.flush()
    approval_id = ""
    if need_approval:
        approval = await approval_service.create(
            db,
            tenant=tenant,
            action="order.refund",
            target=f"{order.platform} {order.outer_id}",
            args={"aftersale_id": row.id, "order_id": order.id, "amount": amount},
            reason=f"退款 {amount / 100:.2f} 元超阈值，转审批：{reason.strip()}",
            applicant=applicant,
            session_id=trace_id,
        )
        approval_id = approval.id
    await db.commit()
    return {
        "aftersale_id": row.id,
        "status": row.status,
        "need_approval": need_approval,
        "approval_id": approval_id,
        "trace_id": trace_id,
    }


async def apply_refund(db: AsyncSession, *, tenant: str, args: dict[str, Any], actor: str) -> None:
    """退款审批通过后的生效动作：售后单置 done、订单转售后中。"""
    aftersale_id = str(args.get("aftersale_id", ""))
    row = (
        await db.execute(
            select(Aftersale).where(Aftersale.tenant == tenant, Aftersale.id == aftersale_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "售后单不存在，无法执行退款", 404)
    order = await _get_order(db, tenant, str(args.get("order_id", "")))
    amount = args.get("amount")
    if not isinstance(amount, int) or amount < 0 or amount > order.total:
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL, "退款金额与订单不一致，已拒绝执行（请核对后重提）"
        )
    row.status = "done"
    order.status = "aftersale"


AFTERSALE_STATUS_LABELS = {"pending": "待处理", "approving": "审批中", "done": "已完成"}


def aftersales_to_dicts(rows: list[Aftersale]) -> list[dict[str, Any]]:
    """售后单出参（列表与详情共用同一口径，含 evidence 证据链）。"""
    return [
        {
            "id": row.id,
            "order_id": row.sales_order_id,
            "reason": row.reason,
            "amount": row.amount,
            "evidence": _evidence_of(row),
            "trace_id": row.trace_id,
            "status": row.status,
            "status_label": AFTERSALE_STATUS_LABELS.get(row.status, row.status),
            "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        }
        for row in rows
    ]


async def list_aftersales(db: AsyncSession, *, tenant: str, limit: int = 50) -> list[Aftersale]:
    stmt = (
        select(Aftersale)
        .where(Aftersale.tenant == tenant)
        .order_by(Aftersale.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars()
    return list(rows)
