"""对账结算服务（日结单列表 + 差异告警 + 日结确认，对齐 API 规范 §4.7 财务节 / 页面设计 §3.14）

链路：endpoints/finance → 本模块 → finance_bills（按 tenant + biz_date 唯一视角）
      → /finance 页：账单表 + 差异红字 + 日结确认。
口径：
- 金额一律整数分；biz_date 存 "YYYY-MM-DD" 文本（字典序即时间序）；
- 差异公式唯一：expected = receivable - refund - fee + freight，diff = received - expected
  （应收减退款减扣点加运费＝应到账，与实收之差即差异；正数=多收，负数=少收）；
- 差异绝对值超 Settings.FINANCE_DIFF_WARN_CENTS 即 diff_warn=true（红字，阈值不进前端硬编码）；
- 日结确认只落 settled_by（财务双人复核为 P2 预留位），重复确认 1001；无 PII 列。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import FinanceBill
from app.services import admin_service

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _dt_text(value: datetime | None) -> str:
    """时间统一口径：空格秒（与订单/商品/审批一致，禁止裸 isoformat）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def expected_receipt(row: FinanceBill) -> int:
    """应到账 = 应收 - 退款 - 扣点 + 运费（差异公式的唯一口径）。"""
    return int(row.receivable) - int(row.refund) - int(row.fee) + int(row.freight)


def bill_to_dict(row: FinanceBill) -> dict[str, Any]:
    diff = int(row.received) - expected_receipt(row)
    return {
        "id": row.id,
        "biz_date": row.biz_date,
        "receivable": int(row.receivable),
        "received": int(row.received),
        "refund": int(row.refund),
        "fee": int(row.fee),
        "freight": int(row.freight),
        "expected": expected_receipt(row),
        "diff": diff,
        "diff_warn": abs(diff) > settings.FINANCE_DIFF_WARN_CENTS,
        "settled_by": row.settled_by,
        "settled": bool(row.settled_by),
        "created_at": _dt_text(row.created_at),
    }


def _check_date(value: str) -> str:
    text = value.strip()
    if not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择账期日（YYYY-MM-DD）")
    if not _DATE_RE.match(text):
        raise BusinessError(ErrorCode.PARAM_INVALID, "账期日格式应为 YYYY-MM-DD")
    return text


async def list_bills(
    db: AsyncSession, *, tenant: str, biz_date: str = "", page: int = 1, size: int = 20
) -> dict[str, Any]:
    """日结单分页列表（biz_date 精确筛选；倒序，最新账期在前）。"""
    stmt = select(FinanceBill).where(FinanceBill.tenant == tenant)
    count_stmt = select(func.count()).select_from(FinanceBill).where(FinanceBill.tenant == tenant)
    text = biz_date.strip()
    if text:
        checked = _check_date(text)
        stmt = stmt.where(FinanceBill.biz_date == checked)
        count_stmt = count_stmt.where(FinanceBill.biz_date == checked)
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = (
        await db.execute(
            stmt.order_by(FinanceBill.biz_date.desc(), FinanceBill.id)
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars()
    items = [bill_to_dict(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        # 阈值随列表下发，前端红字判定与后端同一口径（禁止前端硬编码金额）
        "diff_warn_cents": settings.FINANCE_DIFF_WARN_CENTS,
        "unsettled": sum(1 for item in items if not item["settled"]),
    }


async def settle(db: AsyncSession, *, tenant: str, biz_date: str, actor: str = "") -> FinanceBill:
    """日结确认（按账期日）：未结则落 settled_by，已结重复确认 1001。"""
    checked = _check_date(biz_date)
    row = (
        await db.execute(
            select(FinanceBill).where(FinanceBill.tenant == tenant, FinanceBill.biz_date == checked)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, f"未找到 {checked} 的日结单", 404)
    if row.settled_by:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"{checked} 已由 {row.settled_by} 日结，请勿重复确认"
        )
    row.settled_by = actor or "system"
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="finance.settle",
        target=row.id,
        detail={"biz_date": checked, "diff": int(row.received) - expected_receipt(row)},
    )
    await db.commit()
    return row
