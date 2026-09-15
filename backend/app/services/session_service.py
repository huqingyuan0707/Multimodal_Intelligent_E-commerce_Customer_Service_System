"""会话服务（前置地基：真实落库，对齐 API 规范 §4.3 + 数据模型文档 §2）

链路：endpoints/sessions 薄封装 → 本模块 → sessions/messages 表。
红线：所有查询强制按 (tenant, username) 过滤；跨租户/跨用户一律 404 不泄露存在性。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
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
        "summary": row.summary or "",
        "message_count": message_count,
        "created_at": _dt_text(row.created_at),
        "updated_at": _dt_text(row.updated_at),
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
) -> dict[str, Any]:
    """会话列表分页对象（按人隔离，最近活跃倒序；每行带 message_count）。

    出参 {items, total, page, size} 与知识库/B 端列表同口径（前端 Skill §6 分页）。
    """
    total = (
        await db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.tenant == tenant, Session.username == username)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(Session)
                .where(Session.tenant == tenant, Session.username == username)
                .order_by(Session.updated_at.desc(), Session.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    items = []
    for row in rows:
        count = (
            await db.execute(
                select(func.count()).select_from(Message).where(Message.session_id == row.id)
            )
        ).scalar_one()
        items.append(session_to_dict(row, int(count)))
    return {"items": items, "total": int(total), "page": page, "size": size}


async def create_session(
    db: AsyncSession, *, tenant: str, username: str, title: str = "新会话"
) -> Session:
    """新建会话（标题为空则用默认，前端本地 t-xxx 占位成功后以后端 id 为准）。"""
    row = Session(tenant=tenant, username=username, title=(title or "").strip() or "新会话")
    db.add(row)
    await db.commit()
    return row


async def _owned_session(
    db: AsyncSession, *, tenant: str, username: str, session_id: str
) -> Session:
    """取本人会话行（跨租户/跨用户 404 不泄露存在性，各读操作同源）。"""
    session = (
        await db.execute(
            select(Session).where(
                Session.id == session_id, Session.tenant == tenant, Session.username == username
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    return session


async def get_session_detail(
    db: AsyncSession,
    *,
    tenant: str,
    username: str,
    session_id: str,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    """会话详情（含摘要 + 消息倒序翻页；page=1 为最新页，has_more 供前端加载更早）。

    跨租户/跨用户 404，前端回退 mock 演示；messages 倒序，前端渲染前反转即正序。
    """
    session = await _owned_session(db, tenant=tenant, username=username, session_id=session_id)
    total = (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.session_id == session_id)
        )
    ).scalar_one()
    msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    return {
        "id": session.id,
        "title": session.title,
        "summary": session.summary or "",
        "messages": [message_to_dict(m) for m in msgs],
        "total": int(total),
        "page": page,
        "size": size,
        "has_more": page * size < int(total),
    }


async def rename_session(
    db: AsyncSession, *, tenant: str, username: str, session_id: str, title: str
) -> Session:
    """重命名会话（空标题 1001；顺手刷新活跃时间）。"""
    cleaned = (title or "").strip()
    if not cleaned:
        raise BusinessError(ErrorCode.PARAM_INVALID, "标题不能为空", 400)
    session = await _owned_session(db, tenant=tenant, username=username, session_id=session_id)
    session.title = cleaned[:20]
    await db.commit()
    return session


async def touch_session(db: AsyncSession, *, tenant: str, username: str, session_id: str) -> None:
    """刷新会话活跃时间（每轮落库后调，列表按最近活跃排；flush 不提交由调用方收口）。

    必须显式赋值：ORM onupdate 只在行有变更时触发，纯插消息行不会联动更新 sessions。
    """
    from app.db.base import _now

    session = await _owned_session(db, tenant=tenant, username=username, session_id=session_id)
    session.updated_at = _now()
    await db.flush()


async def delete_session(db: AsyncSession, *, tenant: str, username: str, session_id: str) -> None:
    """删除会话（含消息级联遗忘；不存在 404；附件文件随 media_store TTL 清理不阻塞删除）。"""
    session = await _owned_session(db, tenant=tenant, username=username, session_id=session_id)
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
    modality: str = "text",
    attachments: list[dict[str, Any]] | None = None,
) -> Message:
    """落用户消息行（调用方先经 find_user_message 去重；图文轮 modality=image）。"""
    row = Message(
        session_id=session_id,
        tenant=tenant,
        role="user",
        modality=modality if modality in ("text", "image", "voice") else "text",
        content=content,
        attachments=json.dumps(attachments or [], ensure_ascii=False),
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
    attachments: list[dict[str, Any]] | None = None,
) -> Message:
    """落助手回复行（引用/guard/忠实度/trace 随行持久化，刷新历史可回放；

    图文轮 attachments 存 VLM 检测结果，历史回放直接复原检测卡）。
    """
    row = Message(
        session_id=session_id,
        tenant=tenant,
        role="agent",
        modality="image" if attachments else "text",
        content=content,
        attachments=json.dumps(attachments or [], ensure_ascii=False),
        citations=json.dumps(citations, ensure_ascii=False),
        guard=json.dumps(guard, ensure_ascii=False),
        faithfulness=faithfulness,
        trace_id=trace_id,
        client_msg_id=(client_msg_id or "").strip(),
    )
    db.add(row)
    await db.flush()
    return row
