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
# 流转口径对齐 FRD FR-10.4「待付→待发→已发→签收→完成/售后」：
# - paid 可打单发货（ship）；shipped 可签收（confirm）到 completed，也可直接建售后。
NEXT_ACTIONS: dict[str, tuple[str, ...]] = {
    "pending_pay": (),
    "paid": ("ship",),
    "shipped": ("confirm", "aftersale"),
    "completed": ("aftersale",),
    "aftersale": (),
    "closed": (),
}
# 售后质检处置（FRD FR-10.4「退货质检 → 二次入库 / 报损 / 退供」）
DISPOSITION_PENDING = "pending"
DISPOSITIONS = ("restocked", "scrapped", "returned")
DISPOSITION_LABELS = {
    "restocked": "二次入库",
    "scrapped": "报损",
    "returned": "退供",
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
    data["aftersales"] = aftersales_to_dicts(aftersales)
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


async def confirm(db: AsyncSession, *, tenant: str, order_id: str) -> dict[str, Any]:
    """签收：已发货 → 已完成（FRD 状态机「已发→签收→完成」）。"""
    order = await _get_order(db, tenant, order_id)
    if order.status != "shipped":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"当前状态「{STATUS_LABELS.get(order.status, order.status)}」不可签收，"
            "仅「已发货」订单可确认签收",
        )
    order.status = "completed"
    await db.commit()
    return to_dict(order)


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
    force_approval: bool = False,
) -> dict[str, Any]:
    """发起售后：退款金额超阈值自动转审批（账不动，等批准）。

    force_approval：AI（Agent 工具 refund.create）发起的退款恒进审批，不看金额——
    对齐 FRD 附录 A「refund.create 恒进审批，不直执」与 FR-7；人工后台链路仍走阈值规则
    （默认 False，存量行为不变），避免把「客服按政策小额赔付」也全压到审批队列。
    """
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
    need_approval = force_approval or amount > settings.REFUND_APPROVAL_LIMIT_CENTS
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
            reason=(
                f"AI 发起的退款 {amount / 100:.2f} 元恒进审批：{reason.strip()}"
                if force_approval
                else f"退款 {amount / 100:.2f} 元超阈值，转审批：{reason.strip()}"
            ),
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


async def _aftersale_or_raise(db: AsyncSession, tenant: str, aftersale_id: str) -> Aftersale:
    row = (
        await db.execute(
            select(Aftersale).where(Aftersale.tenant == tenant, Aftersale.id == aftersale_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.ORDER_NOT_FOUND, "售后单不存在或无权访问", 404)
    return row


async def dispose(
    db: AsyncSession,
    *,
    tenant: str,
    aftersale_id: str,
    disposition: str,
    warehouse_id: str = "",
    lines: list[dict[str, Any]] | None = None,
    applicant: str = "",
) -> dict[str, Any]:
    """售后质检处置（FR-10.4：退货质检 → 二次入库 / 报损 / 退供）。

    - restocked（二次入库）：退货质检合格，SKU 重新上架（move_stock in）。
    - scrapped（报损）：恒进审批（红线段「采购/调拨/报损/超阈值退款」），批准后置损。
    - returned（退供）：退回供应商，货物永久离库，不再进入可用池。
    已处置的售后单幂等拒绝（disposition != pending → 3005），业务与审计双击同源。
    """
    if disposition not in DISPOSITIONS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"处置类型非法：{disposition}")
    row = await _aftersale_or_raise(db, tenant, aftersale_id)
    if row.disposition != DISPOSITION_PENDING:
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"该售后单已处置（{DISPOSITION_LABELS.get(row.disposition, row.disposition)}），不可重复处置",
        )
    # 幂等检查：防止审批 pending 期间重复发起处置（同 aftersale_id 已有待审单则拒绝）。
    from app.db.models import Approval

    appr_rows = list(
        (
            await db.execute(
                select(Approval).where(
                    Approval.tenant == tenant,
                    Approval.status == "pending",
                )
            )
        ).scalars()
    )
    if any(
        str((json.loads(r.args or "{}") or {}).get("aftersale_id", "")) == aftersale_id
        for r in appr_rows
        if isinstance(json.loads(r.args or "{}"), dict)
    ):
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            "该售后单已有待审批单，请先完成审批后再处置",
        )
    order = await _get_order(db, tenant, row.sales_order_id)

    if disposition == "scrapped":
        # 报损恒进审批（敏感动作红线），批准后才落 disposition / 审计，账目不动。
        approval = await approval_service.create(
            db,
            tenant=tenant,
            action="aftersale.scrap",
            target=f"{order.platform} {order.outer_id}",
            args={
                "aftersale_id": row.id,
                "order_id": order.id,
                "amount": row.amount,
                "lines": lines or [],
                "warehouse_id": warehouse_id,
            },
            reason=f"退货质检不达标，报损处置：{row.reason}",
            applicant=applicant or row.reason,
            session_id=row.trace_id,
        )
        await db.commit()
        return {
            "aftersale_id": row.id,
            "disposition": "scrapped",
            "disposition_label": DISPOSITION_LABELS["scrapped"],
            "need_approval": True,
            "approval_id": approval.id,
        }

    # 二次入库 / 退供：直接生效。
    # 二次入库 = 货物重新进入可用池；退供 = 货物永久离库（都不再触发库存扣减，
    # 因为退货件从未进入 available 池，见 aftersale 不入库存的既定口径）。
    if disposition == "restocked":
        await _restock_from_items(
            db,
            tenant=tenant,
            order=order,
            lines=lines,
            warehouse_id=warehouse_id,
            aftersale_id=row.id,
            actor=applicant,
        )
    row.disposition = disposition
    row.status = "done"
    await db.commit()
    return {
        "aftersale_id": row.id,
        "disposition": disposition,
        "disposition_label": DISPOSITION_LABELS[disposition],
        "need_approval": False,
        "approval_id": "",
    }


async def _restock_from_items(
    db: AsyncSession,
    *,
    tenant: str,
    order: SalesOrder,
    lines: list[dict[str, Any]] | None,
    warehouse_id: str,
    aftersale_id: str,
    actor: str,
) -> None:
    """二次入库：每次 move_stock in 对应一条 SKU 行快照（items 兜底）。"""
    from app.services import inventory_service

    # 仓库未指定时取该租户第一个仓库（默认仓），与库存列表口径一致。
    wh_id = warehouse_id
    if not wh_id:
        warehouses = await inventory_service.list_warehouses(db, tenant=tenant)
        if not warehouses:
            raise BusinessError(ErrorCode.NOT_FOUND, "该租户没有可用仓库，无法二次入库", 404)
        wh_id = warehouses[0].id
    items = _items_of(order)
    if lines:
        for line in lines:
            sku_id = str(line.get("sku_id") or "").strip()
            qty = int(line.get("qty") or 0)
            if not sku_id:
                raise BusinessError(ErrorCode.PARAM_INVALID, "二次入库明细缺少 sku_id")
            if qty <= 0:
                raise BusinessError(ErrorCode.PARAM_INVALID, f"SKU {sku_id} 的数量必须是正整数")
            await inventory_service.move_stock(
                db,
                tenant=tenant,
                kind="in",
                warehouse_id=wh_id,
                sku_id=sku_id,
                delta=qty,
                reason=f"退货二次入库：售后单 {aftersale_id}",
                actor=actor or "order.qa",
                order_ref=aftersale_id,
            )
    else:
        for item in items:
            sku_id = str(item.get("sku_id") or "")
            qty = int(item.get("qty") or 0)
            if not sku_id or qty <= 0:
                continue
            await inventory_service.move_stock(
                db,
                tenant=tenant,
                kind="in",
                warehouse_id=wh_id,
                sku_id=sku_id,
                delta=qty,
                reason=f"退货二次入库：售后单 {aftersale_id}",
                actor=actor or "order.qa",
                order_ref=aftersale_id,
            )


async def apply_scrap(db: AsyncSession, *, tenant: str, args: dict[str, Any], actor: str) -> None:
    """报损审批通过后的生效动作：售后单置 done + disposition=scrapped。"""
    aftersale_id = str(args.get("aftersale_id", ""))
    row = (
        await db.execute(
            select(Aftersale).where(Aftersale.tenant == tenant, Aftersale.id == aftersale_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.ORDER_NOT_FOUND, "售后单不存在，无法执行报损", 404)
    if row.disposition != DISPOSITION_PENDING:
        raise BusinessError(ErrorCode.ORDER_STATE_ILLEGAL, "该售后单已处置，报损批准重复执行")
    row.disposition = "scrapped"
    row.status = "done"


AFTERSALE_STATUS_LABELS = {"pending": "待处理", "approving": "审批中", "done": "已完成"}


def aftersales_to_dicts(rows: list[Aftersale]) -> list[dict[str, Any]]:
    """售后单出参（列表与详情共用同一口径，含证据链与质检处置位）。"""
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
            "disposition": row.disposition,
            "disposition_label": DISPOSITION_LABELS.get(row.disposition, row.disposition),
            "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        }
        for row in rows
    ]


async def list_aftersales(
    db: AsyncSession,
    *,
    tenant: str,
    status: str = "",
    disposition: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """售后单服务端分页列表（前端红线：所有列表页必须服务端分页）。"""
    stmt = select(Aftersale).where(Aftersale.tenant == tenant)
    if status:
        if status not in AFTERSALE_STATUS_LABELS:
            raise BusinessError(ErrorCode.PARAM_INVALID, f"售后状态非法：{status}")
        stmt = stmt.where(Aftersale.status == status)
    if disposition:
        if disposition not in DISPOSITIONS and disposition != DISPOSITION_PENDING:
            raise BusinessError(ErrorCode.PARAM_INVALID, f"处置类型非法：{disposition}")
        stmt = stmt.where(Aftersale.disposition == disposition)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Aftersale.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": aftersales_to_dicts(rows),
    }
