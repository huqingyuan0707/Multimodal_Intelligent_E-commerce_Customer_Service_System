"""Mining 闭环服务（第 13 步，对齐 RAG 规范 §4/§5 + 数据模型 §2）

链路：问答落库 → feedback（差评/拒答/低忠实度）→ candidates 聚类
      → 运营补知识 → reindex → 回归评测。
红线：全部按 tenant 隔离；审计只追加；候选只读不自动改知识（运营确认后才入库）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback, Message
from app.services import rag_governance

# ---------------- 反馈写入 ----------------


async def submit_feedback(
    db: AsyncSession,
    *,
    tenant: str,
    actor: str,
    message_id: str,
    session_id: str = "",
    vote: str = "down",
    comment: str = "",
) -> Feedback:
    """记一条反馈（租户隔离；message 归属必须同租户，否则 404 不泄露存在性）。"""
    from app.core.exceptions import BusinessError, ErrorCode

    msg = (
        await db.execute(
            select(Message).where(Message.id == message_id, Message.tenant == tenant)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "消息不存在或无权访问", 404)
    row = Feedback(
        tenant=tenant,
        message_id=message_id,
        session_id=session_id or msg.session_id,
        vote=(vote or "down").strip() or "down",
        comment=(comment or "").strip()[:500],
    )
    db.add(row)
    await db.flush()
    await rag_governance.audit_write(
        db,
        tenant=tenant,
        actor=actor,
        action="mining.feedback",
        target=message_id,
        detail={"vote": row.vote, "session_id": row.session_id},
    )
    await db.commit()
    return row


# ---------------- 候选挖掘 ----------------


async def list_candidates(
    db: AsyncSession, *, tenant: str, limit: int = 20
) -> list[dict[str, Any]]:
    """待补知识候选：本租户差评 + 无引用拒答消息（按时间倒序，运营逐条确认补库）。"""
    fb_rows = list(
        (
            await db.execute(
                select(Feedback)
                .where(Feedback.tenant == tenant)
                .order_by(Feedback.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    msg_ids = [f.message_id for f in fb_rows]
    msgs = (
        list(
            (await db.execute(select(Message).where(Message.id.in_(msg_ids)))).scalars()
        )
        if msg_ids
        else []
    )
    by_id = {m.id: m for m in msgs}
    out: list[dict[str, Any]] = []
    for fb in fb_rows:
        msg = by_id.get(fb.message_id)
        out.append(
            {
                "feedback_id": fb.id,
                "message_id": fb.message_id,
                "session_id": fb.session_id,
                "vote": fb.vote,
                "comment": fb.comment,
                "query": msg.content if msg and msg.role == "agent" else (msg.content if msg else ""),
                "created_at": fb.created_at.isoformat(sep=" ", timespec="seconds")
                if fb.created_at
                else "",
            }
        )
    # 拒答消息（引用为空的 agent 行）补位：反馈不足时运营仍可见缺口
    if len(out) < limit:
        rej = list(
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.tenant == tenant,
                        Message.role == "agent",
                        Message.citations == "[]",
                    )
                    .order_by(Message.created_at.desc())
                    .limit(limit - len(out))
                )
            ).scalars()
        )
        for m in rej:
            if any(c["message_id"] == m.id for c in out):
                continue
            out.append(
                {
                    "feedback_id": "",
                    "message_id": m.id,
                    "session_id": m.session_id,
                    "vote": "rejected",
                    "comment": "",
                    "query": m.content[:200],
                    "created_at": m.created_at.isoformat(sep=" ", timespec="seconds")
                    if m.created_at
                    else "",
                }
            )
    return out


async def count_feedbacks(db: AsyncSession, *, tenant: str) -> int:
    """租户反馈总数（运营看板口径）。"""
    total = (
        await db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.tenant == tenant)
        )
    ).scalar_one()
    return int(total)
