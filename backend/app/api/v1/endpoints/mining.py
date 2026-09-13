"""Mining 闭环端点（第 13 步，对齐 RAG 规范 §4/§5 + API 规范 §4.4）

链路：POST /mining/feedback（差评落库+审计）→ GET /mining/candidates（待补知识）
      → 运营补知识 → POST /documents/reindex → 回归评测。
红线：全部按 tenant 隔离；message 跨租户 404。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import get_current_user
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import mining_service

router = APIRouter(prefix="/mining", tags=["mining"])


class FeedbackRequest(BaseModel):
    """反馈入参（端点私有 DTO；vote 仅收 up/down）。"""

    message_id: str
    vote: str = "down"
    comment: str = ""


@router.post("/feedback")
async def submit_feedback(
    payload: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """提交反馈（差评进候选池；vote 非 down 按 down 归一）。"""
    vote = (payload.vote or "down").strip() or "down"
    row = await mining_service.submit_feedback(
        db,
        tenant=user.tenant,
        actor=user.username,
        message_id=payload.message_id.strip(),
        vote=vote,
        comment=payload.comment,
    )
    return ok({"id": row.id}, "反馈已收到，将用于改进回答")


@router.get("/candidates")
async def list_candidates(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """待补知识候选（差评 + 无引用拒答，租户隔离倒序）。"""
    items = await mining_service.list_candidates(db, tenant=user.tenant)
    total = await mining_service.count_feedbacks(db, tenant=user.tenant)
    return ok({"items": items, "total": total}, "获取成功")
