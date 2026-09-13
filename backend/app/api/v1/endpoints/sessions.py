"""会话端点（真实落库，对齐 API 规范 §4.3）

链路：GET/POST /sessions → session_service（tenant+username 口径）→ ok()。
前端本地先建 t-xxx 占位，成功后以后端 id 为准；详情 404 回退 mock。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

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
) -> dict[str, Any]:
    """会话列表（真实空数据 [] 不报错；page/size 默认 20 预留分页）。"""
    items = await session_service.list_sessions(
        db, tenant=user.tenant, username=user.username, page=page, size=size
    )
    return ok(items, "获取成功")


@router.post("")
async def create_session(
    payload: CreateSessionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """会话详情（含消息；跨租户 404，前端回退 mock）。"""
    return ok(
        await session_service.get_session_detail(
            db, tenant=user.tenant, username=user.username, session_id=session_id
        ),
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
