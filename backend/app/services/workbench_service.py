"""坐席工作台服务（C 步转人工：待接队列 + 认领/转接/解决 + 内部备注 + 代回 + Trace，对齐 FRD FR-7）

链路：endpoints/workbench 薄封装 → 本模块 → sessions/session_notes/messages 表。
边界：本模块只做坐席侧流转动作与查询；自动挂起与触发判据不在本模块
（见 handoff_service.auto_handoff + handoff_rules 规则表），二者不得互抄一份。
红线：队列/详情/备注只看本租户（tenant 过滤）；买家转人工走 handoff 的 owner 口径，
其余动作仅坐席（endpoint 用 require_any_perm("cs", "admin") 拦截，本模块再验一遍）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.core.observability import snapshot as obs_snapshot
from app.core.user_context import CurrentUser
from app.db.base import _now
from app.db.models import Message, Session, SessionNote
from app.services import context_service, session_service

# ---------------- 状态口径 ----------------

HANDOFF_STATUSES = ("none", "pending", "handling", "resolved")

HANDOFF_LABELS = {
    "none": "未转人工",
    "pending": "待接",
    "handling": "处理中",
    "resolved": "已解决",
}

OPEN_STATUSES = ("pending", "handling")

NOTE_MAX_LEN = 500
REPLY_MAX_LEN = 2000


def is_agent(user: CurrentUser) -> bool:
    """坐席口径（与路由 meta.roles 同源：cs/admin 及其通配；买家走 handoff owner 口）。"""
    return "*" in user.roles or "cs" in user.roles or "admin" in user.roles


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def handoff_to_dict(row: Session, message_count: int = 0, last_message: str = "") -> dict[str, Any]:
    """队列/详情行（含流转态 + 中文标签；last_message 为最新一条预览 40 字）。"""
    base = session_service.session_to_dict(row, message_count)
    base.update(
        {
            "username": row.username,
            "handoff_status": row.handoff_status or "none",
            "handoff_label": HANDOFF_LABELS.get(row.handoff_status or "none", "未转人工"),
            "assignee": row.assignee or "",
            "handoff_reason": row.handoff_reason or "",
            "resolution": row.resolution or "",
            "last_message": (last_message or "")[:40],
        }
    )
    return base


def note_to_dict(row: SessionNote) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "author": row.author or "",
        "content": row.content or "",
        "created_at": _dt_text(row.created_at),
    }


async def _tenant_session(db: AsyncSession, *, tenant: str, session_id: str) -> Session:
    """租户内取会话行（坐席视角：跨本租户任何买家；跨租户 404 不泄露存在性）。"""
    row = (
        await db.execute(select(Session).where(Session.id == session_id, Session.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    return row


async def _message_count(db: AsyncSession, session_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(Message).where(Message.session_id == session_id)
            )
        ).scalar_one()
    )


async def _last_message(db: AsyncSession, session_id: str) -> str:
    row = (
        await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.content if row is not None else ""


# ---------------- 待接队列 ----------------


async def queue(
    db: AsyncSession,
    *,
    tenant: str,
    status: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """待接队列（租户级：坐席看全量买家会话；最近活跃倒序；空数据 items=[]）。

    status："" / "open" → 待接+处理中；pending/handling/resolved 精确过滤，其余 1001。
    keyword：标题/买家用户名模糊匹配（订单号搜索走订单页，前端队列内再筛）。
    """
    wanted: tuple[str, ...] = OPEN_STATUSES
    if status in ("", "open"):
        wanted = OPEN_STATUSES
    elif status in HANDOFF_STATUSES:
        wanted = (status,)
    else:
        raise BusinessError(ErrorCode.PARAM_INVALID, "队列状态非法", 400)
    stmt = select(Session).where(Session.tenant == tenant, Session.handoff_status.in_(wanted))
    key = (keyword or "").strip()
    if key:
        like = f"%{key}%"
        stmt = stmt.where(or_(Session.title.ilike(like), Session.username.ilike(like)))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = list(
        (
            await db.execute(
                stmt.order_by(Session.updated_at.desc(), Session.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    items = []
    for row in rows:
        items.append(
            handoff_to_dict(
                row,
                await _message_count(db, row.id),
                await _last_message(db, row.id),
            )
        )
    return {"items": items, "total": total, "page": page, "size": size}


# ---------------- 流转动作 ----------------


async def handoff(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, reason: str = ""
) -> Session:
    """标记转人工（买家自助走 owner 口径：仅本人会话；坐席可标任意本租户会话）。

    none/resolved→pending（解决后可重开）；handling 中重复标记只刷新原因不断流。
    """
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    if row.username != user.username and not is_agent(user):
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    cleaned = (reason or "").strip()[:200]
    if row.handoff_status in ("none", "resolved"):
        row.handoff_status = "pending"
        row.assignee = ""
    if cleaned:
        row.handoff_reason = cleaned
    await db.commit()
    return row


async def claim(db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str) -> Session:
    """抢接（pending/none→handling + assignee=本人；已被他人认领 1001 明示只读围观）。

    并发安全：认领用「条件 UPDATE + rowcount」做原子比较交换，两个坐席同抢同一会话时
    只有一个 UPDATE 命中（另一人 rowcount=0 → 重读后拿到「已被 XX 接管」），不会互相覆盖。
    自己已认领的会话重复点认领 = 幂等刷新（updated_at 前移），不报错。
    """
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可认领", 400)
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(Session)
        .where(
            Session.id == session_id,
            Session.tenant == tenant,
            or_(
                Session.handoff_status.in_(("pending", "none")),
                (Session.handoff_status == "handling")
                & (Session.assignee.in_(("", user.username))),
            ),
        )
        .values(handoff_status="handling", assignee=user.username, updated_at=_now())
    )
    if result.rowcount == 0:
        # 抢接失败：会话已被他人接管（或状态在读取后被改），重读拿真实归属再报错
        await db.rollback()
        current = await _tenant_session(db, tenant=tenant, session_id=session_id)
        if current.handoff_status == "resolved":
            raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可认领", 400)
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"已被 {current.assignee or '其他坐席'} 接管，转为只读围观",
            400,
        )
    await db.commit()
    await db.refresh(row)
    # 接起事件（E 步可观测）：observability 据此算「挂起→接起」耗时 = 30s 接起率分母/分子
    record(
        "handoff.claim",
        {"tenant": tenant, "session_id": session_id, "assignee": user.username},
    )
    return row


async def transfer(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, assignee: str
) -> Session:
    """转接（assignee 必填；pending 顺手进入 handling；已解决不可转）。"""
    target = (assignee or "").strip()
    if not target:
        raise BusinessError(ErrorCode.PARAM_INVALID, "转接坐席不能为空", 400)
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可转接", 400)
    row.assignee = target
    if row.handoff_status == "pending":
        row.handoff_status = "handling"
    await db.commit()
    return row


async def resolve(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, conclusion: str = ""
) -> Session:
    """解决归档（handling/pending→resolved + 解决小结；重复解决 1001）。"""
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决", 400)
    row.handoff_status = "resolved"
    row.resolution = (conclusion or "").strip()[:500]
    await db.commit()
    return row


# ---------------- 运营指标（E 步可观测：GET /workbench/metrics） ----------------


async def metrics_view(db: AsyncSession, *, tenant: str) -> dict[str, Any]:
    """坐席运营指标：可观测内存聚合（接起率/工具成功率/降级率）+ 本租户队列存量。

    口径：进程内滑窗（observability 重启清零，JSONL 留历史）；队列存量走 DB 实况。
    30s 接起率 = handoff.claim 距挂起 ≤ 目标秒数 / 认领总数（目标见 Settings）。
    """
    counts: dict[str, int] = {}
    for status in HANDOFF_STATUSES:
        counts[status] = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Session)
                    .where(Session.tenant == tenant, Session.handoff_status == status)
                )
            ).scalar_one()
        )
    return {"observability": obs_snapshot(), "queue": counts}


# ---------------- 坐席代回 ----------------


async def reply(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, content: str
) -> dict[str, Any]:
    """坐席代回（handling 会话追加 agent 行：引用空、guard 标人工、trace 新起）。

    未认领先认领（1001 明示）；内容 1..2000 字；买家侧历史回放即见，无需重进队列。
    """
    text = (content or "").strip()
    if not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "回复内容不能为空", 400)
    if len(text) > REPLY_MAX_LEN:
        raise BusinessError(ErrorCode.PARAM_INVALID, "回复内容超长（限 2000 字）", 400)
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    if row.handoff_status != "handling":
        raise BusinessError(ErrorCode.PARAM_INVALID, "请先认领会话再代回", 400)
    saved = await session_service.save_agent_message(
        db,
        tenant=tenant,
        session_id=row.id,
        content=text,
        citations=[],
        guard={"pass": True, "by": "agent", "agent": user.username},
        faithfulness=1.0,
        trace_id=uuid.uuid4().hex[:16],
        client_msg_id=f"cs-{user.username}-{uuid.uuid4().hex[:8]}",
    )
    row.updated_at = _now()
    await db.commit()
    return session_service.message_to_dict(saved)


# ---------------- 内部备注 ----------------


async def list_notes(db: AsyncSession, *, tenant: str, session_id: str) -> list[dict[str, Any]]:
    """备注列表（创建时间正序；买家无查询口，天生不可见）。"""
    await _tenant_session(db, tenant=tenant, session_id=session_id)
    rows = list(
        (
            await db.execute(
                select(SessionNote)
                .where(SessionNote.tenant == tenant, SessionNote.session_id == session_id)
                .order_by(SessionNote.created_at.asc(), SessionNote.id.asc())
            )
        ).scalars()
    )
    return [note_to_dict(r) for r in rows]


async def add_note(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, content: str
) -> dict[str, Any]:
    """写备注（内容 1..500 字；author 取 Token 用户名）。"""
    text = (content or "").strip()
    if not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "备注内容不能为空", 400)
    if len(text) > NOTE_MAX_LEN:
        raise BusinessError(ErrorCode.PARAM_INVALID, "备注超长（限 500 字）", 400)
    await _tenant_session(db, tenant=tenant, session_id=session_id)
    row = SessionNote(tenant=tenant, session_id=session_id, author=user.username, content=text)
    db.add(row)
    await db.commit()
    return note_to_dict(row)


# ---------------- Trace 详情 ----------------


async def trace_view(
    db: AsyncSession, *, tenant: str, session_id: str, size: int = 50
) -> dict[str, Any]:
    """坐席 Trace 详情（会话行 + 最新消息含引用/trace + 上下文用量，同源可验）。

    口径与买家侧 get_session_detail/context 完全同源（同 message_to_dict、
    同 load_window/build_history_block），坐席所见即买家所得。
    """
    row = await _tenant_session(db, tenant=tenant, session_id=session_id)
    msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(max(1, min(size, 200)))
            )
        ).scalars()
    )
    window = await context_service.load_window(db, session_id=row.id)
    _block, stats = context_service.build_history_block(window, row.summary or "")
    return {
        "session": handoff_to_dict(row, await _message_count(db, row.id)),
        "messages": [session_service.message_to_dict(m) for m in reversed(msgs)],
        "context": {
            "summary": row.summary or "",
            "rounds": stats["rounds"],
            "tokens": stats["tokens"],
            "dropped": stats["dropped"],
            "budget": settings.SESSION_TOKEN_BUDGET,
            "window_rounds": settings.SESSION_HISTORY_ROUNDS,
        },
    }
