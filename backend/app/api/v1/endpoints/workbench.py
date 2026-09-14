"""坐席工作台端点（C 步转人工联调，对齐 API 规范 §4.11 + 页面设计 §3.2）

链路：WorkbenchView → 本模块薄封装（解析→调 workbench_service→ok()）→ sessions/session_notes。
权限：handoff 买家自助（owner 口）/坐席代标；其余仅 cs/admin（require_any_perm）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import get_current_user, require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import workbench_service

router = APIRouter(prefix="/workbench", tags=["workbench"])

CS = require_any_perm("cs", "admin")


class HandoffRequest(BaseModel):
    """转人工入参（原因可选，限 200 字）。"""

    reason: str = ""


class TransferRequest(BaseModel):
    """转接入参（目标坐席用户名必填）。"""

    assignee: str = ""


class ResolveRequest(BaseModel):
    """解决入参（小结可选，限 500 字）。"""

    conclusion: str = ""


class NoteRequest(BaseModel):
    """备注入参（内容 1..500 字）。"""

    content: str = ""


class ReplyRequest(BaseModel):
    """代回入参（内容 1..2000 字，落 agent 行买家可见）。"""

    content: str = ""


@router.get("/queue")
async def get_queue(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
    status: str = Query(default="", max_length=16),
    q: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """待接队列（租户级分页对象；status 空/open=待接+处理中；q 搜标题/买家）。"""
    return ok(
        await workbench_service.queue(
            db, tenant=user.tenant, status=status, keyword=q, page=page, size=size
        ),
        "获取成功",
    )


@router.post("/sessions/{session_id}/handoff")
async def handoff_session(
    session_id: str,
    payload: HandoffRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """标记转人工（买家点转人工自助；坐席可代标本租户任意会话）。"""
    row = await workbench_service.handoff(
        db,
        tenant=user.tenant,
        user=user,
        session_id=session_id,
        reason=payload.reason if payload else "",
    )
    return ok(workbench_service.handoff_to_dict(row), "已转人工，坐席将在 30 秒内接管")


@router.post("/sessions/{session_id}/claim")
async def claim_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """抢接（pending→handling + 认领到本人；被他人认领 1001 明示围观）。"""
    row = await workbench_service.claim(db, tenant=user.tenant, user=user, session_id=session_id)
    return ok(workbench_service.handoff_to_dict(row), "认领成功，已接管会话")


@router.post("/sessions/{session_id}/transfer")
async def transfer_session(
    session_id: str,
    payload: TransferRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """转接（换认领人；已解决不可转）。"""
    row = await workbench_service.transfer(
        db, tenant=user.tenant, user=user, session_id=session_id, assignee=payload.assignee
    )
    return ok(workbench_service.handoff_to_dict(row), "转接成功")


@router.post("/sessions/{session_id}/resolve")
async def resolve_session(
    session_id: str,
    payload: ResolveRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """解决归档（→resolved + 解决小结；解决后可被买家再次转人工重开）。"""
    row = await workbench_service.resolve(
        db,
        tenant=user.tenant,
        user=user,
        session_id=session_id,
        conclusion=payload.conclusion if payload else "",
    )
    return ok(workbench_service.handoff_to_dict(row), "会话已解决归档")


@router.post("/sessions/{session_id}/reply")
async def reply_session(
    session_id: str,
    payload: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """坐席代回（handling 会话追加人工回复，买家历史即见；未认领 1001）。"""
    return ok(
        await workbench_service.reply(
            db, tenant=user.tenant, user=user, session_id=session_id, content=payload.content
        ),
        "回复已发送",
    )


@router.get("/sessions/{session_id}/notes")
async def list_notes(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """内部备注列表（创建时间正序；买家无查询口）。"""
    return ok(
        await workbench_service.list_notes(db, tenant=user.tenant, session_id=session_id),
        "获取成功",
    )


@router.post("/sessions/{session_id}/notes")
async def add_note(
    session_id: str,
    payload: NoteRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
) -> dict[str, Any]:
    """写内部备注（买家不可见）。"""
    return ok(
        await workbench_service.add_note(
            db, tenant=user.tenant, user=user, session_id=session_id, content=payload.content
        ),
        "备注已保存",
    )


@router.get("/sessions/{session_id}/trace")
async def trace_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(CS),
    size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """坐席 Trace 详情（会话流转态 + 消息引用/trace + 上下文用量，与买家侧同源）。"""
    return ok(
        await workbench_service.trace_view(
            db, tenant=user.tenant, session_id=session_id, size=size
        ),
        "获取成功",
    )
