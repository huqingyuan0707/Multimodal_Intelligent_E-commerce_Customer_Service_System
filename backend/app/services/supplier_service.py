"""供应商服务（账期 + 历史合格率，对齐 API 规范 §4.7 采购节 / 页面设计 §3.12）

链路：endpoints/purchase（/suppliers）→ 本模块 → suppliers 表；procurement_service 建单时复用校验。
口径：
- 名称必填（租户内不去重：同名不同法人主体合法，由合格率/账期区分）；
- pass_rate 落库为 0~1 浮点，展示交前端格式化，服务端不存百分数字符串。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Supplier


def _dt_text(value: datetime | None) -> str:
    """时间统一口径：空格秒（与订单/商品/审批一致，禁止裸 isoformat）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def supplier_to_dict(row: Supplier) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "pay_terms": row.pay_terms,
        "pass_rate": round(float(row.pass_rate or 0.0), 4),
        "created_at": _dt_text(row.created_at),
    }


async def supplier_or_raise(db: AsyncSession, *, tenant: str, supplier_id: str) -> Supplier:
    """按 id 取供应商（跨租户 404，采购建单前必查）。"""
    row = (
        await db.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant == tenant)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "供应商不存在或无权访问", 404)
    return row


async def supplier_names(db: AsyncSession, *, ids: list[str]) -> dict[str, str]:
    """批量取供应商名（采购单列表避免 N+1）。"""
    wanted = [one for one in ids if one]
    if not wanted:
        return {}
    rows = (
        await db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(wanted)))
    ).all()
    return {str(one_id): str(name) for one_id, name in rows}


async def list_suppliers(
    db: AsyncSession, *, tenant: str, keyword: str = "", page: int = 1, size: int = 20
) -> dict[str, Any]:
    """供应商分页列表（名称模糊筛选，账期/合格率随行返回）。"""
    stmt = select(Supplier).where(Supplier.tenant == tenant)
    count_stmt = select(func.count()).select_from(Supplier).where(Supplier.tenant == tenant)
    text = keyword.strip()
    if text:
        stmt = stmt.where(Supplier.name.like(f"%{text}%"))
        count_stmt = count_stmt.where(Supplier.name.like(f"%{text}%"))
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = (
        await db.execute(
            stmt.order_by(Supplier.created_at.desc(), Supplier.id)
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars()
    return {
        "items": [supplier_to_dict(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    }


async def create_supplier(
    db: AsyncSession, *, tenant: str, name: str, pay_terms: str = "", pass_rate: float = 1.0
) -> Supplier:
    """新建供应商（名称必填；合格率须在 0~1）。"""
    text = name.strip()
    if not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写供应商名称")
    if not 0.0 <= pass_rate <= 1.0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "合格率需在 0~1 之间（填 0.98 表示 98%）")
    row = Supplier(
        tenant=tenant, name=text, pay_terms=pay_terms.strip(), pass_rate=round(pass_rate, 4)
    )
    db.add(row)
    await db.commit()
    return row
