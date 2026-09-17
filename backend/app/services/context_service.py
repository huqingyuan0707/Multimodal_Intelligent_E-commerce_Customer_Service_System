"""会话上下文管理（三层之 Context，对齐 FR-1.4 + 数据模型 §2）

链路：run_text_turn → load_window（最近 N 轮）→ 超限 summarize_window（规则摘要写
      sessions.summary）→ build_history_block（摘要 + 窗口 + 多模态转写）→
      answer 拼进 LLM → done.context 回 token 用量。
双重修剪：轮数 SESSION_HISTORY_ROUNDS（默认 20）+ Token 预算 SESSION_TOKEN_BUDGET
          （默认 8000）；超限摘要压缩 + sanitize_text PII 正则清洗。
口径统一：estimate_tokens 中文 1.5 字/token，与成本估算同源，禁止各处自定除数。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.pii import CTRL, EMAIL, IDCARD, MOBILE
from app.db.models import Message, Session
from app.services import memory_service

# ---------------- Token 估算 ----------------


def estimate_tokens(text: str) -> int:
    """中文 1.5 字/token 估算（纯函数）：成本归因与预算裁剪同源，禁止各处自定除数。"""
    return max(1, (len(text or "") * 2 + 2) // 3)


# ---------------- PII 清洗 ----------------
# 正则唯一出处 app.core.pii（记忆守门共用，禁止此处再写一份）。


def sanitize_text(text: str, limit: int = 0) -> str:
    """历史进 LLM 前清洗（纯函数）：手机/身份证/邮箱脱敏 + 控制字符清理 + 截断。

    脱敏口径与售中展示一致（138****1234）；limit>0 则截断，默认不截由调用方定预算。
    """
    cleaned = CTRL.sub("", text or "")
    cleaned = MOBILE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], cleaned)
    cleaned = IDCARD.sub(lambda m: m.group(0)[:6] + "********" + m.group(0)[-4:], cleaned)
    cleaned = EMAIL.sub("***@***", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    width = limit if limit and limit > 0 else settings.SESSION_MSG_CHARS
    return cleaned[:width]


# ---------------- 窗口加载 ----------------


async def load_window(db: AsyncSession, *, session_id: str, rounds: int = 0) -> list[Message]:
    """取最近 N 轮消息（正序；user+agent 配对算一轮，落库中途行也计入保证连续）。

    rounds<=0 取 Settings.SESSION_HISTORY_ROUNDS；调用方传更大值做摘要源。
    """
    keep = rounds if rounds and rounds > 0 else settings.SESSION_HISTORY_ROUNDS
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(keep * 2 + 2)
            )
        ).scalars()
    )
    rows.reverse()
    return rows


def _attachment_line(item: dict[str, object]) -> str:
    """多模态附件转写一行（纯函数）：图/音附件进历史不再是黑盒。"""
    category = str(item.get("category", ""))
    if category:
        raw: object = item.get("confidence", 0.0)
        conf = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0
        return f"[图：{category} {conf:.2f}]"
    file_id = str(item.get("file_id", ""))
    if file_id:
        return f"[附件 {file_id[:8]}]"
    text = str(item.get("text", ""))
    return f"[语音转写：{text[:40]}]" if text else ""


def message_line(row: Message) -> str:
    """单条历史转写（含多模态附件行；纯函数可单测）。"""
    try:
        attachments = json.loads(row.attachments or "")
    except ValueError:
        attachments = []
    extra = "".join(_attachment_line(a) for a in attachments if isinstance(a, dict))
    who = "用户" if row.role == "user" else "客服"
    return f"{who}：{sanitize_text(row.content)}{extra}"


# ---------------- 摘要 ----------------


def summarize_window(rows: list[Message], max_chars: int = 0) -> str:
    """规则摘要（纯函数，离线可用）：首问 + 轮数 + 末轮 + 多模态定级，不调模型不断流。

    长会话（>ROUNDS 轮）被摘要掉的老消息只留此摘要进 LLM，而非逐条注入。
    """
    width = max_chars if max_chars and max_chars > 0 else settings.SESSION_SUMMARY_CHARS
    if not rows:
        return ""
    users = [r for r in rows if r.role == "user"]
    first_q = sanitize_text(users[0].content, 120) if users else ""
    last = message_line(rows[-1])[:160] if rows else ""
    defects: list[str] = []
    for r in rows:
        try:
            attachments = json.loads(r.attachments or "")
        except ValueError:
            continue
        for a in attachments:
            if isinstance(a, dict) and a.get("category") not in (None, "", "无瑕疵"):
                defects.append(str(a.get("category")))
    defect_part = f"；涉及瑕疵：{','.join(dict.fromkeys(defects))}" if defects else ""
    rounds = (len(rows) + 1) // 2
    return f"共{rounds}轮，首问“{first_q}”{defect_part}；近况：{last}"[:width]


async def refresh_summary(db: AsyncSession, *, session: Session, window: int = 0) -> str:
    """窗口超限时重算摘要并落库（调用方在落库新消息后调；返回新摘要）。

    取全量窗口外老消息做摘要源：查最近 (ROUNDS+10)*2 行，前 ROUNDS*2 行留给窗口，
    剩下全进摘要，保证摘要只增量前移不丢信息。
    """
    keep = window if window and window > 0 else settings.SESSION_HISTORY_ROUNDS
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit((keep + 10) * 2)
            )
        ).scalars()
    )
    rows.reverse()
    overflow = rows[: max(0, len(rows) - keep * 2)]
    if not overflow:
        return session.summary or ""
    session.summary = summarize_window(overflow)
    await db.flush()
    return session.summary


# ---------------- 拼装 ----------------


async def assemble(db: AsyncSession, *, session: Session) -> tuple[str, dict[str, int], str]:
    """上下文装配（run_text_turn 唯一入口）：快照命中直返 → 窗口 → 摘要 → 块（摘要刷新随事务提交）。

    块顺序：【上文摘要】→【长期偏好】→【用户近况】→【历史对话】；记忆块钉死不参与丢轮
    （预算只裁窗口行，记忆是跨轮高信号）；stats 加 memory_recent/memory_prefs/snapshot
    计数透给 done.context（加法，向后兼容）。
    返回 (history_block, {rounds, tokens, dropped, memory_recent, memory_prefs, snapshot}, summary)。
    """
    updated = session.updated_at.isoformat() if session.updated_at else ""
    snap = await memory_service.snapshot_read(session.tenant, session.username, session.id, updated)
    if snap is not None:
        stats = dict(snap["stats"])
        stats["snapshot"] = 1
        return snap["block"], stats, snap["summary"]
    window = await load_window(db, session_id=session.id)
    cap = settings.SESSION_HISTORY_ROUNDS * 2 + 2
    summary = session.summary or ""
    if len(window) >= cap:
        summary = await refresh_summary(db, session=session) or summary
        window = window[-settings.SESSION_HISTORY_ROUNDS * 2 :]
    prefs = await memory_service.recall_prefs(db, tenant=session.tenant, username=session.username)
    recent = await memory_service.recall_short(session.tenant, session.username)
    extra = tuple(
        b
        for b in (
            memory_service.render_prefs(prefs),
            memory_service.render_recent(recent),
        )
        if b
    )
    block, stats = build_history_block(window, summary, extra_blocks=extra)
    stats["memory_recent"] = len(recent)
    stats["memory_prefs"] = len(prefs)
    stats["snapshot"] = 0
    await memory_service.snapshot_write(
        session.tenant,
        session.username,
        session.id,
        updated_at=updated,
        block=block,
        stats={k: int(v) for k, v in stats.items() if k != "snapshot"},
        summary=summary,
    )
    return block, stats, summary


def build_history_block(
    window: list[Message],
    summary: str = "",
    budget: int = 0,
    extra_blocks: tuple[str, ...] = (),
) -> tuple[str, dict[str, int]]:
    """拼历史块（纯函数）：【上文摘要】+ 记忆块（偏好/近况，钉死）+【历史对话】近 N 轮。

    超预算从旧往新丢窗口行，记忆块不参与裁剪；空窗口且无块返回 ("", {0,0,0})。
    返回 (block, {rounds, tokens, dropped})。
    """
    cap = budget if budget and budget > 0 else settings.SESSION_TOKEN_BUDGET
    summary_part = f"【上文摘要】\n{(summary or '').strip()}\n" if (summary or "").strip() else ""
    pinned = "".join(f"{b.rstrip()}\n" for b in extra_blocks if b and b.strip())
    pinned_tokens = estimate_tokens(summary_part + pinned)
    lines = [message_line(r) for r in window]
    dropped = 0
    while lines and pinned_tokens + estimate_tokens("\n".join(lines)) > cap:
        lines.pop(0)
        dropped += 1
    if not lines and not summary_part and not pinned:
        return "", {"rounds": 0, "tokens": 0, "dropped": 0}
    body = "\n".join(lines)
    head = f"{summary_part}{pinned}".rstrip("\n")
    block = f"{head}\n【历史对话】\n{body}" if body else head
    rounds = (len(lines) + 1) // 2
    return block, {"rounds": rounds, "tokens": estimate_tokens(block), "dropped": dropped}


async def describe(db: AsyncSession, *, session: Session) -> dict[str, Any]:
    """上下文视图口径（GET context / workbench trace 同源：窗口+摘要+记忆块，只读不写快照）。

    与 assemble 同一 composer（recall + build_history_block），坐席所见即 LLM 所算；
    快照是纯性能缓存，不影响视图内容。
    """
    window = await load_window(db, session_id=session.id)
    prefs = await memory_service.recall_prefs(db, tenant=session.tenant, username=session.username)
    recent = await memory_service.recall_short(session.tenant, session.username)
    extra = tuple(
        b
        for b in (
            memory_service.render_prefs(prefs),
            memory_service.render_recent(recent),
        )
        if b
    )
    _block, stats = build_history_block(window, session.summary or "", extra_blocks=extra)
    return {
        "summary": session.summary or "",
        "rounds": stats["rounds"],
        "tokens": stats["tokens"],
        "dropped": stats["dropped"],
        "memory_recent": len(recent),
        "memory_prefs": len(prefs),
        "budget": settings.SESSION_TOKEN_BUDGET,
        "window_rounds": settings.SESSION_HISTORY_ROUNDS,
    }
