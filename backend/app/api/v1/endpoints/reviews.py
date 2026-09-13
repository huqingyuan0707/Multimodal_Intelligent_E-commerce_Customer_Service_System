"""评价端点（列表/回复/一键建工单，对齐 API 规范 §4.8）

链路：前端 ReviewView → 本模块 → review_service → reviews/tickets。
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
from app.services import review_service

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewCreateRequest(BaseModel):
    """评价入库入参（平台同步/手工补录）。"""

    platform: str = ""
    outer_id: str = ""
    level: str = "good"
    content: str = ""
    tags: list[str] | None = None


class ReplyRequest(BaseModel):
    """评价回复入参。"""

    reply: str


class ReviewTicketRequest(BaseModel):
    """差评建工单入参（assignee 为空则待认领）。"""

    assignee: str = ""


@router.get("")
async def list_reviews(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("review:read", "review:write")),
    level: str = Query(default="", max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """评价列表（level=bad 看差评盘）。"""
    rows = await review_service.list_reviews(db, tenant=user.tenant, level=level, limit=limit)
    return ok([review_service.review_to_dict(r) for r in rows], "获取成功")


@router.post("")
async def create_review(
    payload: ReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("review:write")),
) -> dict[str, Any]:
    """评价入库。"""
    row = await review_service.create_review(
        db,
        tenant=user.tenant,
        platform=payload.platform,
        outer_id=payload.outer_id,
        level=payload.level,
        content=payload.content,
        tags=payload.tags,
    )
    await db.commit()
    return ok(review_service.review_to_dict(row), "评价已入库")


@router.post("/{review_id}/reply")
async def reply_review(
    review_id: str,
    payload: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("review:write")),
) -> dict[str, Any]:
    """评价回复（置 replied）。"""
    row = await review_service.reply_review(
        db, tenant=user.tenant, review_id=review_id, reply=payload.reply
    )
    await db.commit()
    return ok(review_service.review_to_dict(row), "回复成功")


@router.post("/{review_id}/ticket")
async def create_review_ticket(
    review_id: str,
    payload: ReviewTicketRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("review:write")),
) -> dict[str, Any]:
    """差评一键建工单（SLA 2h，ticket_id 回写评价双向可跳；已有则回放）。"""
    ticket, review = await review_service.create_review_ticket(
        db, tenant=user.tenant, review_id=review_id, assignee=payload.assignee
    )
    await db.commit()
    return ok(
        {
            "ticket": review_service.ticket_to_dict(ticket),
            "review": review_service.review_to_dict(review),
        },
        "工单已创建",
    )
