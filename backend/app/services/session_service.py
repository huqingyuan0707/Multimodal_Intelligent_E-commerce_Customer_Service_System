"""会话服务（前置地基：真实落库，对齐 API 规范 §4.3 + 数据模型文档 §2）

链路：endpoints/sessions 薄封装 → 本模块 → sessions/messages 表。
红线：所有查询强制按 (tenant, username) 过滤；跨租户/跨用户一律 404 不泄露存在性。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Message, Session


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def session_to_dict(row: Session, message_count: int = 0) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "created_at": _dt_text(row.created_at),
        "message_count": message_count,
    }


def message_to_dict(row: Message) -> dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "modality": row.modality,
        "content": row.content,
        "attachments": _parse_json(row.attachments, []),
        "citations": _parse_json(row.citations, []),
        "trace_id": row.trace_id,
        "created_at": _dt_text(row.created_at),
    }


async def list_sessions(
    db: AsyncSession, *, tenant: str, username: str, page: int = 1, size: int = 20
) -> list[dict[str, Any]]:
    """会话列表（按人隔离，倒序；page/size 预留分页，暂返回数组保持前端兼容）。"""
    stmt = (
        select(Session)
        .where(Session.tenant == tenant, Session.username == username)
        .order_by(Session.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [session_to_dict(r) for r in rows]


async def create_session(
    db: AsyncSession, *, tenant: str, username: str, title: str = "新会话"
) -> Session:
    """新建会话（标题为空则用默认，前端本地 t-xxx 占位成功后以后端 id 为准）。"""
    row = Session(tenant=tenant, username=username, title=(title or "").strip() or "新会话")
    db.add(row)
    await db.commit()
    return row


async def get_session_detail(
    db: AsyncSession, *, tenant: str, username: str, session_id: str
) -> dict[str, Any]:
    """会话详情（含消息；跨租户/跨用户 404，前端 404 回退 mock 演示）。"""
    session = (
        await db.execute(
            select(Session).where(
                Session.id == session_id, Session.tenant == tenant, Session.username == username
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
            )
        ).scalars()
    )
    return {
        "id": session.id,
        "title": session.title,
        "messages": [message_to_dict(m) for m in msgs],
    }


async def delete_session(db: AsyncSession, *, tenant: str, username: str, session_id: str) -> None:
    """删除会话（含消息级联遗忘；不存在 404）。"""
    session = (
        await db.execute(
            select(Session).where(
                Session.id == session_id, Session.tenant == tenant, Session.username == username
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    msgs = list(
        (await db.execute(select(Message).where(Message.session_id == session_id))).scalars()
    )
    for m in msgs:
        await db.delete(m)
    await db.delete(session)
    await db.commit()
