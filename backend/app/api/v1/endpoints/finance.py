"""对账端点（日结单列表 + 日结确认，对齐 API 规范 §4.7 财务节）

链路：前端 /finance → 本模块（解析入参 + 组装信封）→ finance_service → finance_bills。
权限：读 `finance:read|write`、写 `finance:write`；差异阈值由服务层随列表下发，前端不硬编码。
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
from app.services import finance_service

router = APIRouter(prefix="/finance", tags=["finance"])


class SettleRequest(BaseModel):
    """日结确认（按账期日；财务双人复核为 P2 预留位）。"""

    biz_date: str


@router.get("/bills")
async def list_bills(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("finance:read", "finance:write")),
    biz_date: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """日结单分页列表（应收/实收/退款/运费/扣点/差异 + 超阈值红字标记）。"""
    data = await finance_service.list_bills(
        db, tenant=user.tenant, biz_date=biz_date, page=page, size=size
    )
    return ok(data, "获取成功")


@router.post("/settle")
async def settle(
    payload: SettleRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("finance:write")),
) -> dict[str, Any]:
    """日结确认（重复确认 1001；已结账单不覆盖原确认人）。"""
    row = await finance_service.settle(
        db, tenant=user.tenant, biz_date=payload.biz_date, actor=user.username
    )
    return ok(finance_service.bill_to_dict(row), f"{row.biz_date} 已完成日结确认")
