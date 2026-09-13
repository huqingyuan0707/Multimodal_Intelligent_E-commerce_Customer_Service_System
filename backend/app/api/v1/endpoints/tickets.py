"""工单端点（列表/转交/关闭，对齐 API 规范 §4.8）

链路：前端（ReviewView 建单 → 本模块查/转/关）→ review_service → tickets。
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

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TransferRequest(BaseModel):
    """转交入参。"""

    assignee: str


class CloseRequest(BaseModel):
    """关闭入参（结论必填，沉淀知识）。"""

    conclusion: str


@router.get("")
async def list_tickets(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("ticket:read", "ticket:write")),
    status: str = Query(default="", max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """工单列表（逾期由前端按 sla_due 算红条）。"""
    rows = await review_service.list_tickets(db, tenant=user.tenant, status=status, limit=limit)
    return ok([review_service.ticket_to_dict(r) for r in rows], "获取成功")


@router.post("/{ticket_id}/transfer")
async def transfer_ticket(
    ticket_id: str,
    payload: TransferRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("ticket:write")),
) -> dict[str, Any]:
    """工单转交（已关闭不可转）。"""
    row = await review_service.transfer_ticket(
        db, tenant=user.tenant, ticket_id=ticket_id, assignee=payload.assignee
    )
    await db.commit()
    return ok(review_service.ticket_to_dict(row), "转交成功")


@router.post("/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    payload: CloseRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("ticket:write")),
) -> dict[str, Any]:
    """工单关闭（结论必填；已关闭不可重关）。"""
    row = await review_service.close_ticket(
        db, tenant=user.tenant, ticket_id=ticket_id, conclusion=payload.conclusion
    )
    await db.commit()
    return ok(review_service.ticket_to_dict(row), "工单已关闭")
