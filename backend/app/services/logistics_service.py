"""物流服务（公司/单号查询/异常转售后，对齐 FRD FR-10.7/附录 D + API 规范 §4.8）

链路：endpoints/logistics → 本模块 → logistics_orders（异常自动建售后单走 order_service）。
红线：异常转售后必须关联 sales_order；裸单号查不到返回 NOT_FOUND 中文提示。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import LogisticsOrder
from app.services import order_service

COMPANIES = ("顺丰", "中通", "圆通", "韵达", "申通", "京东", "邮政", "德邦")
EXCEPTION_KINDS = ("stuck", "damaged", "rejected")
EXCEPTION_LABELS = {"stuck": "滞留", "damaged": "破损", "rejected": "拒收"}


def logistics_to_dict(row: LogisticsOrder) -> dict[str, Any]:
    return {
        "id": row.id,
        "sales_order_id": row.sales_order_id,
        "company": row.company,
        "tracking_no": row.tracking_no,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


async def track(db: AsyncSession, *, tenant: str, tracking_no: str) -> dict[str, Any]:
    """单号查询（本地镜像；平台实时轨迹 P2 对接）。"""
    row = (
        await db.execute(
            select(LogisticsOrder).where(
                LogisticsOrder.tenant == tenant,
                LogisticsOrder.tracking_no == tracking_no.strip(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "查不到该运单号")
    return logistics_to_dict(row)


async def mark_exception(
    db: AsyncSession,
    *,
    tenant: str,
    logistics_id: str,
    kind: str,
    applicant: str,
) -> dict[str, Any]:
    """异常登记：状态置 exception + 自动建售后单（关联 trace 留空待客服回填）。"""
    if kind not in EXCEPTION_KINDS:
        raise BusinessError(ErrorCode.PARAM_INVALID, "异常类型非法")
    row = (
        await db.execute(
            select(LogisticsOrder).where(
                LogisticsOrder.id == logistics_id, LogisticsOrder.tenant == tenant
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "运单不存在")
    row.status = "exception"
    aftersale = await order_service.create_aftersale(
        db,
        tenant=tenant,
        order_id=row.sales_order_id,
        reason=f"物流异常:{EXCEPTION_LABELS[kind]}",
        amount=0,
        trace_id="",
        applicant=applicant,
    )
    await db.flush()
    return {"logistics": logistics_to_dict(row), "aftersale_id": aftersale["aftersale_id"]}
