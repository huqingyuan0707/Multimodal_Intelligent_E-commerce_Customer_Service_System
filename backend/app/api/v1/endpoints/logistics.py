"""物流端点（公司/单号查询/异常转售后，对齐 API 规范 §4.8）

链路：前端 LogisticsView → 本模块 → logistics_service → logistics_orders（+ aftersales）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import logistics_service

router = APIRouter(prefix="/logistics", tags=["logistics"])


class ExceptionRequest(BaseModel):
    """异常登记入参（自动建售后单）。"""

    logistics_id: str
    kind: str


@router.get("/companies")
async def list_companies(
    user: CurrentUser = Depends(require_any_perm("order:read", "order:fulfill")),
) -> dict[str, Any]:
    """快递公司列表（运费模板 P2）。"""
    _ = user
    return ok([{"name": c} for c in logistics_service.COMPANIES], "获取成功")


class TrackRequest(BaseModel):
    """单号查询入参。"""

    tracking_no: str


@router.post("/track")
async def track(
    payload: TrackRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:read", "order:fulfill")),
) -> dict[str, Any]:
    """单号查询（本地镜像；平台实时轨迹 P2）。"""
    data = await logistics_service.track(db, tenant=user.tenant, tracking_no=payload.tracking_no)
    return ok(data, "获取成功")


@router.post("/exceptions")
async def mark_exception(
    payload: ExceptionRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:fulfill")),
) -> dict[str, Any]:
    """异常登记：状态置 exception + 自动建售后单。"""
    data = await logistics_service.mark_exception(
        db,
        tenant=user.tenant,
        logistics_id=payload.logistics_id,
        kind=payload.kind,
        applicant=user.username,
    )
    await db.commit()
    return ok(data, "异常已登记并建售后单")
