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


async def ensure_session(
    db: AsyncSession, *, tenant: str, username: str, thread_id: str | None, title_hint: str
) -> tuple[Session, bool]:
    """对话轮次会话归位：thread_id 命中本人会话则复用，否则新建（标题取问题前 20 字）。

    他人/异租户 thread_id 视为未传直接新建，不泄露存在性。返回 (会话, 是否新建)。
    """
    tid = (thread_id or "").strip()
    if tid:
        owned = (
            await db.execute(
                select(Session).where(
                    Session.id == tid,
                    Session.tenant == tenant,
                    Session.username == username,
                )
            )
        ).scalar_one_or_none()
        if owned is not None:
            return owned, False
    title = (title_hint or "").strip()[:20] or "新会话"
    row = Session(tenant=tenant, username=username, title=title)
    db.add(row)
    await db.flush()
    return row, True


async def find_user_message(
    db: AsyncSession, *, session_id: str, client_msg_id: str
) -> Message | None:
    """按幂等键找已落库的用户消息（重连复用，不再插新行）。"""
    if not (client_msg_id or "").strip():
        return None
    return (
        await db.execute(
            select(Message).where(
                Message.session_id == session_id,
                Message.role == "user",
                Message.client_msg_id == client_msg_id.strip(),
            )
        )
    ).scalar_one_or_none()


async def find_agent_message(
    db: AsyncSession, *, session_id: str, client_msg_id: str
) -> Message | None:
    """按幂等键找已落库的助手回复（重放用：直接复用内容与 trace_id，不再调模型）。"""
    if not (client_msg_id or "").strip():
        return None
    return (
        await db.execute(
            select(Message).where(
                Message.session_id == session_id,
                Message.role == "agent",
                Message.client_msg_id == client_msg_id.strip(),
            )
        )
    ).scalar_one_or_none()


async def save_user_message(
    db: AsyncSession,
    *,
    tenant: str,
    session_id: str,
    content: str,
    client_msg_id: str = "",
) -> Message:
    """落用户消息行（调用方先经 find_user_message 去重）。"""
    row = Message(
        session_id=session_id,
        tenant=tenant,
        role="user",
        modality="text",
        content=content,
        client_msg_id=(client_msg_id or "").strip(),
    )
    db.add(row)
    await db.flush()
    return row


async def save_agent_message(
    db: AsyncSession,
    *,
    tenant: str,
    session_id: str,
    content: str,
    citations: list[dict[str, object]],
    guard: dict[str, object],
    faithfulness: float,
    trace_id: str,
    client_msg_id: str = "",
) -> Message:
    """落助手回复行（引用/guard/忠实度/trace 随行持久化，刷新历史可回放）。"""
    row = Message(
        session_id=session_id,
        tenant=tenant,
        role="agent",
        modality="text",
        content=content,
        citations=json.dumps(citations, ensure_ascii=False),
        guard=json.dumps(guard, ensure_ascii=False),
        faithfulness=faithfulness,
        trace_id=trace_id,
        client_msg_id=(client_msg_id or "").strip(),
    )
    db.add(row)
    await db.flush()
    return row
