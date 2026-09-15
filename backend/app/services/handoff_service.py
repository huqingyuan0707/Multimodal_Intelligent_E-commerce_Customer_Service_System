"""转人工触发与挂起（C 步规则表唯一挂载点，对齐 API 规范 §4.11 + FRD FR-7）

职责：自动「该不该转人工」的判据入口——组信号（补齐连续未解决 / 连续降级计数）→ 规则表
      handoff_rules.evaluate → 命中且会话仍空闲（none）才置 pending。
链路：chat_service 落库段 / agent runtime 收敛段 → auto_handoff() → handoff_rules（规则本体）
      → sessions.handoff_status: none→pending + handoff_reason（坐席队列即见）。
红线：规则与阈值分别住在 services/handoff_rules.py 与 Settings.HANDOFF_*，本文件只做挂载不写死判据；
     只 flush 不 commit，由调用方统一提交（保证「消息 + 挂起 + 成本审计」落库原子）；
     已认领 / 已解决一律不抢（handoff_status != none 即 applied=false，只记可观测不覆盖原因）。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import record
from app.db.models import Message, Session
from app.services import handoff_rules

# ---------------- 挂起动作 ----------------


async def mark_pending_if_idle(
    db: AsyncSession, *, tenant: str, session_id: str, reason: str
) -> None:
    """自动挂起（会话仍空闲 none 才置 pending；pending/handling/resolved 一律不抢）。

    只 flush 不提交，由调用方（chat_service._persist_* / runtime._settle）统一 commit。
    """
    row = (
        await db.execute(select(Session).where(Session.id == session_id, Session.tenant == tenant))
    ).scalar_one_or_none()
    if row is None or (row.handoff_status or "none") != "none":
        return
    row.handoff_status = "pending"
    row.handoff_reason = (reason or "").strip()[:200]
    await db.flush()


# ---------------- 规则表挂载点（C 步） ----------------


async def recent_guards(
    db: AsyncSession, *, session_id: str, limit: int = 10, exclude_client_msg_id: str = ""
) -> list[dict[str, Any]]:
    """最近 agent 行的 guard（新→旧），供规则表做连续计数。

    exclude_client_msg_id：排除本轮（已落库时传本轮幂等键，避免与 current_guard 重复计一次）。
    """
    stmt = select(Message.guard).where(Message.session_id == session_id, Message.role == "agent")
    key = (exclude_client_msg_id or "").strip()
    if key:
        stmt = stmt.where(Message.client_msg_id != key)
    rows = list(
        (
            await db.execute(
                stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                    max(1, min(limit, 50))
                )
            )
        ).scalars()
    )
    guards: list[dict[str, Any]] = []
    for raw in rows:
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            guards.append(parsed)
    return guards


async def auto_handoff(
    db: AsyncSession,
    *,
    tenant: str,
    session_id: str,
    signals: dict[str, Any] | None = None,
    current_guard: dict[str, Any] | None = None,
    exclude_client_msg_id: str = "",
) -> dict[str, Any]:
    """规则表统一挂载点：自动「该不该转人工」全站只走这里（对话落库与 Agent 编排共用）。

    组信号（补齐连续计数）→ handoff_rules.evaluate → 命中且会话仍空闲（none）才挂 pending；
    已认领/已解决不抢（可观测记录里记 applied=false 供排查）。只 flush 不 commit，
    由调用方统一提交，保证「消息 + 挂起 + 成本审计」落库原子。
    """
    guards = await recent_guards(
        db, session_id=session_id, exclude_client_msg_id=exclude_client_msg_id
    )
    if isinstance(current_guard, dict) and current_guard:
        guards = [current_guard, *guards]
    data: dict[str, Any] = dict(signals or {})
    data.setdefault("miss_streak", handoff_rules.missed_streak(guards))
    data.setdefault("degrade_streak", handoff_rules.streak(guards, "degraded"))

    decision = handoff_rules.evaluate(data)
    status = ""
    applied = False
    if decision["hit"]:
        row = (
            await db.execute(
                select(Session).where(Session.id == session_id, Session.tenant == tenant)
            )
        ).scalar_one_or_none()
        status = (row.handoff_status or "none") if row is not None else ""
        if row is not None and status == "none":
            await mark_pending_if_idle(
                db, tenant=tenant, session_id=session_id, reason=decision["reason"]
            )
            status = "pending"
            applied = True
        record(
            "handoff",
            {
                "tenant": tenant,
                "session_id": session_id,
                "rule": decision["code"],
                "matched": decision["matched"],
                "applied": applied,
                "handoff_status": status,
            },
        )
    decision["applied"] = applied
    decision["handoff_status"] = status
    decision["session_id"] = session_id
    return decision


def handoff_rules_view() -> dict[str, Any]:
    """规则表只读视图（GET /workbench/handoff-rules）：规则清单 + 阈值 + 总开关快照。"""
    return {
        "enabled": bool(settings.HANDOFF_ENABLED),
        "miss_streak_threshold": settings.HANDOFF_MISS_STREAK_THRESHOLD,
        "degrade_streak_threshold": settings.HANDOFF_DEGRADE_STREAK_THRESHOLD,
        "rules": handoff_rules.rule_table(),
    }


def blank_handoff(
    session: Any = None, *, session_id: str = "", handoff_status: str = ""
) -> dict[str, Any]:
    """「本轮未发生自动挂起」的规整返回（空问题帧 / 重放帧用），形状与 auto_handoff 未命中一致。

    重放不重判规则表（判定已在首答时执行并落 sessions），但 done 帧的 handoff 字段不能消失，
    故给稳定帧形；传 session 行时按会话当前流转态填 `session_id`/`handoff_status`。
    """
    if session is not None:
        session_id = str(getattr(session, "id", "") or "")
        handoff_status = str(getattr(session, "handoff_status", "") or "none")
    return {
        **handoff_rules.blank_decision(bool(settings.HANDOFF_ENABLED)),
        "applied": False,
        "handoff_status": handoff_status,
        "session_id": session_id,
    }
