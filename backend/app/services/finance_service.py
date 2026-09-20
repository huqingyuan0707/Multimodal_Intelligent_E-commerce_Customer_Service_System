"""对账结算服务（日结单列表 + 差异告警 + 日结制单/复核两步，对齐 API 规范 §4.7 财务节 / 页面设计 §3.14）

链路：endpoints/finance → 本模块 → finance_bills（按 tenant + biz_date 唯一视角）
      → /finance 页：账单表 + 差异红字 + 日结制单 + 复核结清。
口径：
- 金额一律整数分；biz_date 存 "YYYY-MM-DD" 文本（字典序即时间序）；
- 差异公式唯一：expected = receivable - refund - fee + freight，diff = received - expected
  （应收减退款减扣点加运费＝应到账，与实收之差即差异；正数=多收，负数=少收）；
- 差异绝对值超 Settings.FINANCE_DIFF_WARN_CENTS 即 diff_warn=true（红字，阈值不进前端硬编码）；
- **双人复核两步（FR-10.5 制单与复核分离）**：settle 落 settled_by（制单），confirm_settle 落
  reviewed_by/reviewed_at（复核结清）；复核人不得与制单人同一账号（同人 1001）；出参
  settled = reviewed_by 非空（复核完成才算已结算）；无 PII 列。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.base import _now
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
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _dt_text(row.reviewed_at),
        # settled 出参口径 = 复核完成（reviewed_by 非空），仅制单未复核仍是「待复核」
        "settled": bool(row.reviewed_by),
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
    """日结制单（第一步）：未制单则落 settled_by，已制单重复提交 1001（账单不存在 404）。"""
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
            ErrorCode.PARAM_INVALID, f"{checked} 已由 {row.settled_by} 制单，请勿重复制单"
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


async def confirm_settle(
    db: AsyncSession, *, tenant: str, biz_date: str, actor: str = ""
) -> FinanceBill:
    """日结复核（第二步，FR-10.5 双人复核）：换人复核通过才落 reviewed_by 置已结算。

    红线：制单人与复核人不得为同一账号（同人 1001，与知识库「发布需换人复核」同口径）；
    未制单 1001、已复核重复 1001、账单不存在 404。
    """
    checked = _check_date(biz_date)
    row = (
        await db.execute(
            select(FinanceBill).where(FinanceBill.tenant == tenant, FinanceBill.biz_date == checked)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, f"未找到 {checked} 的日结单", 404)
    if not row.settled_by:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"{checked} 尚未制单，请先执行日结制单")
    if row.reviewed_by:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"{checked} 已由 {row.reviewed_by} 复核结清，请勿重复复核"
        )
    maker = row.settled_by
    if actor and actor == maker:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"双人复核红线：{checked} 由 {maker} 制单，制单人与复核人不能为同一人，请换人复核",
        )
    row.reviewed_by = actor or "system"
    row.reviewed_at = _now()
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="finance.settle_review",
        target=row.id,
        detail={
            "biz_date": checked,
            "maker": maker,
            "diff": int(row.received) - expected_receipt(row),
        },
    )
    await db.commit()
    return row
