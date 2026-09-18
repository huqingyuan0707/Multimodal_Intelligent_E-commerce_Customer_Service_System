"""风控端点（拦截复核：通过/拦截，对齐 API 规范 §4.8 风控节）

链路：前端 /risk → 本模块（解析入参 + 组装信封）→ risk_service → risk_events。
权限：`risk:review`（复核是人工动作，不做全自动封号）；工单中心复用既有 /tickets 端点。
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
from app.services import risk_service

router = APIRouter(prefix="/risk", tags=["risk"])


class ReviewRequest(BaseModel):
    """复核结论（拦截理由必填，合规留痕）。"""

    reason: str = ""


@router.get("/events")
async def list_events(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("risk:review", "risk:read")),
    status: str = Query(default="", max_length=16),
    kind: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """风控事件分页列表（关联图谱摘要随行返回；pending 为待复核数）。"""
    data = await risk_service.list_events(
        db, tenant=user.tenant, status=status, kind=kind, page=page, size=size
    )
    return ok(data, "获取成功")


@router.post("/{event_id}/pass")
async def pass_event(
    event_id: str,
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("risk:review")),
) -> dict[str, Any]:
    """复核放行（仅待复核可处理；重复复核 3005）。"""
    row = await risk_service.review_event(
        db,
        tenant=user.tenant,
        event_id=event_id,
        block=False,
        reason=payload.reason,
        reviewer=user.username,
    )
    return ok(risk_service.event_to_dict(row), "已放行")


@router.post("/{event_id}/block")
async def block_event(
    event_id: str,
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("risk:review")),
) -> dict[str, Any]:
    """复核拦截（理由必填；只落复核结论，不自动封号、不改 users.status）。"""
    row = await risk_service.review_event(
        db,
        tenant=user.tenant,
        event_id=event_id,
        block=True,
        reason=payload.reason,
        reviewer=user.username,
    )
    return ok(risk_service.event_to_dict(row), "已拦截并留痕，处置请走人工流程")
