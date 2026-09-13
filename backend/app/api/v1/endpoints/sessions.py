"""会话端点（三层之 Session，对齐 API 规范 §4.3 + 数据模型 §2）

链路：GET/POST /sessions → session_service（tenant+username 口径）→ ok()。
列表分页对象 + 详情消息翻页 + 重命名 + 上下文视图；前端本地先建 t-xxx 占位，
成功后以后端 id 为准；详情 404 回退 mock。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rbac import get_current_user
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    """新建会话入参（标题可选，为空用默认）。"""

    title: str = "新会话"


@router.get("")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> object:
    """会话列表分页对象（最近活跃倒序，每行带 message_count；空数据 items=[] 不报错）。"""
    return ok(
        await session_service.list_sessions(
            db, tenant=user.tenant, username=user.username, page=page, size=size
        ),
        "获取成功",
    )


@router.post("")
async def create_session(
    payload: CreateSessionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """新建会话（落库后返回 id；空 body 用默认标题，兼容旧 stub 调用）。"""
    title = (payload.title if payload else "") or "新会话"
    row = await session_service.create_session(
        db, tenant=user.tenant, username=user.username, title=title
    )
    return ok(session_service.session_to_dict(row), "会话已创建")


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> object:
    """会话详情（含摘要 + 消息倒序翻页；page=1 最新页，has_more 供加载更早）。

    跨租户 404，前端回退 mock；messages 倒序，前端渲染前反转即正序。
    """
    return ok(
        await session_service.get_session_detail(
            db,
            tenant=user.tenant,
            username=user.username,
            session_id=session_id,
            page=page,
            size=size,
        ),
        "获取成功",
    )


class RenameSessionRequest(BaseModel):
    """重命名入参（端点私有 DTO；空标题 1001）。"""

    title: str = ""


@router.put("/{session_id}")
async def rename_session(
    session_id: str,
    payload: RenameSessionRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """重命名会话（抽屉行内改名；跨租户 404）。"""
    row = await session_service.rename_session(
        db,
        tenant=user.tenant,
        username=user.username,
        session_id=session_id,
        title=payload.title,
    )
    return ok(session_service.session_to_dict(row), "标题已更新")


@router.get("/{session_id}/context")
async def get_session_context(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """上下文视图（三层之 Context：摘要 + 窗口轮数 + Token 估算 + 预算，供坐席 Trace 调试）。

    口径与 run_text_turn 装配完全同源（同 load_window/build_history_block），所见即所算。
    """
    from app.services import context_service

    session = await session_service._owned_session(
        db, tenant=user.tenant, username=user.username, session_id=session_id
    )
    window = await context_service.load_window(db, session_id=session.id)
    _block, stats = context_service.build_history_block(window, session.summary or "")
    return ok(
        {
            "summary": session.summary or "",
            "rounds": stats["rounds"],
            "tokens": stats["tokens"],
            "dropped": stats["dropped"],
            "budget": settings.SESSION_TOKEN_BUDGET,
            "window_rounds": settings.SESSION_HISTORY_ROUNDS,
        },
        "获取成功",
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """删除会话（含消息级联遗忘）。"""
    await session_service.delete_session(
        db, tenant=user.tenant, username=user.username, session_id=session_id
    )
    return ok({"id": session_id}, "会话已删除")
