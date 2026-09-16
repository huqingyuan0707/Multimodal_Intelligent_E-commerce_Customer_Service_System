"""会话质检打分与坐席绩效（C 步收官：FRD FR-7「质检打分、绩效统计」，对齐数据模型 §2 session_scores）

链路：坐席 resolve → endpoints/workbench 后台任务 auto_score_session → 本模块
      LLM-as-judge（llm_service 单出口，模型不可用降级规则兜底，绝不 500）
      → session_scores 落一行（一会话一行，重评覆盖）→ GET score / performance 读取；
      坐席人工改评走 score_session(manual=...)，source=manual 留 reviewer。
红线：判分口径唯一出处在本模块（prompt/解析/兜底/绩效聚合），端点只做薄封装；
     judge 原文截断进 detail 留证可回溯；可观测记 quality.score 事件（接起率同族口径）。
对齐：API 规范 §4.11、FRD FR-7、执行步骤 C 步。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.db.base import _now
from app.db.models import Message, Session, SessionScore

# ---------------- 纯函数：prompt / 解析 / 规则兜底 ----------------

_JUDGE_SYSTEM = (
    "你是电商客服质检员。给你一段已解决的客服会话（含买家消息、AI/坐席回复与解决小结），"
    "请从「问题解决度、答复准确性、服务态度、流程规范」四个维度综合打分。"
    "只输出一个 JSON 对象，不要任何其他文字："
    '{"score": 1到5的整数, "resolution_ok": true或false, '
    '"dimensions": {"resolution": 1到5, "accuracy": 1到5, "attitude": 1到5, "process": 1到5}, '
    '"reason": "一句话中文依据"}'
)

_JSON_RE = re.compile(r"\{.*\}", re.S)


def build_transcript(messages: list[dict[str, Any]], resolution: str) -> str:
    """会话转写（judge 输入）：role: content 逐行，超长截断控 token；附解决小结。"""
    limit = max(4, int(settings.QUALITY_MAX_MESSAGES or 40))
    lines: list[str] = []
    for msg in messages[-limit:]:
        role = "买家" if msg.get("role") == "user" else "客服"
        body = str(msg.get("content") or "").strip()[:500]
        if body:
            lines.append(f"{role}：{body}")
    if resolution:
        lines.append(f"解决小结：{resolution[:300]}")
    return "\n".join(lines)


def parse_judge_output(text: str) -> dict[str, Any] | None:
    """解析 judge 输出为规整评分字典；结构不对/分数越界一律返回 None（走兜底）。"""
    match = _JSON_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    raw_score = data.get("score")
    if raw_score is None:
        return None
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        return None
    if not 1 <= score <= 5:
        return None
    raw_dims = data.get("dimensions")
    dims: dict[str, Any] = raw_dims if isinstance(raw_dims, dict) else {}
    return {
        "score": score,
        "resolution_ok": bool(data.get("resolution_ok")),
        "dimensions": {k: _clamp5(v) for k, v in dims.items() if k in _DIM_KEYS},
        "reason": str(data.get("reason") or "")[:200],
    }


_DIM_KEYS = ("resolution", "accuracy", "attitude", "process")


def _clamp5(value: Any) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def rule_fallback(messages: list[dict[str, Any]], resolution: str) -> dict[str, Any]:
    """规则兜底评分（模型不可用时）：以可机检信号粗判，宁可保守不夸大。

    基线 3 分：坐席/有据回复 +1、解决小结非空 +1、末轮拒答或降级 -1、全程无客服回复 -1；
    钳到 1..5。resolution_ok 仅在有解决小结时为真（无小结不判已解决）。
    """
    agent_msgs = [m for m in messages if m.get("role") == "agent"]
    score = 3
    notes: list[str] = ["规则兜底（模型不可用）"]
    if agent_msgs:
        score += 1
    else:
        score -= 1
        notes.append("无客服回复")
    if resolution:
        score += 1
    last_guard = _guard_of(agent_msgs[-1]) if agent_msgs else {}
    if last_guard.get("rejected") or last_guard.get("degraded"):
        score -= 1
        notes.append("末轮拒答/降级")
    return {
        "score": max(1, min(5, score)),
        "resolution_ok": bool(resolution),
        "dimensions": {},
        "reason": "；".join(notes)[:200],
    }


def _guard_of(msg: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(msg.get("guard") or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------- 序列化 ----------------


def score_to_dict(row: SessionScore) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    try:
        loaded = json.loads(row.detail or "{}")
        detail = loaded if isinstance(loaded, dict) else {}
    except ValueError:
        pass
    return {
        "id": row.id,
        "session_id": row.session_id,
        "assignee": row.assignee or "",
        "score": int(row.score or 0),
        "resolution_ok": bool(row.resolution_ok),
        "source": row.source or "",
        "reviewer": row.reviewer or "",
        "detail": detail,
        "pass": bool(row.score) and int(row.score) >= int(settings.QUALITY_PASS_SCORE),
        "updated_at": row.updated_at.isoformat(sep=" ", timespec="seconds")
        if row.updated_at
        else "",
    }


# ---------------- 服务：取数 / 评分 / 落库 ----------------


async def _session_row(db: AsyncSession, *, tenant: str, session_id: str) -> Session:
    row = (
        await db.execute(select(Session).where(Session.id == session_id, Session.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    return row


async def _transcript(db: AsyncSession, session_id: str) -> list[dict[str, Any]]:
    msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        ).scalars()
    )
    return [
        {"role": m.role, "content": m.content, "guard": m.guard}
        for m in msgs
        if (m.content or "").strip()
    ]


async def score_session(
    db: AsyncSession,
    *,
    tenant: str,
    session_id: str,
    manual: dict[str, Any] | None = None,
    reviewer: str = "",
) -> dict[str, Any]:
    """给会话打质检分并落库（一会话一行，重评覆盖）。

    manual 非空 = 人工改评（score 1..5 必填，跳过模型）；否则 LLM-as-judge，
    模型不可用/输出不可解析 → 规则兜底（source=rule），全程绝不抛 500。
    """
    row = await _session_row(db, tenant=tenant, session_id=session_id)
    messages = await _transcript(db, session_id)
    resolution = (row.resolution or "").strip()
    source, reviewer_name = "judge", ""
    if manual is not None:
        raw = manual.get("score")
        try:
            value = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            value = 0
        if not 1 <= value <= 5:
            raise BusinessError(ErrorCode.PARAM_INVALID, "质检分数须为 1..5 的整数", 400) from None
        judged: dict[str, Any] = {
            "score": value,
            # 未显式给 resolution_ok（None）时沿用「有解决小结即视为已解决」口径
            "resolution_ok": bool(manual["resolution_ok"])
            if manual.get("resolution_ok") is not None
            else bool(resolution),
            "dimensions": {},
            "reason": str(manual.get("comment") or "坐席人工改评")[:200],
        }
        source, reviewer_name = "manual", reviewer
    else:
        judged_by_llm = await _judge(messages, resolution)
        if judged_by_llm is None:
            judged = rule_fallback(messages, resolution)
            source = "rule"
        else:
            judged = judged_by_llm
    detail = {**judged, "messages": len(messages)}
    existing = (
        await db.execute(
            select(SessionScore).where(
                SessionScore.tenant == tenant, SessionScore.session_id == session_id
            )
        )
    ).scalar_one_or_none()
    target = existing or SessionScore(tenant=tenant, session_id=session_id)
    target.assignee = row.assignee or ""
    target.score = int(judged["score"])
    target.resolution_ok = 1 if judged["resolution_ok"] else 0
    target.source = source
    target.reviewer = reviewer_name
    target.detail = json.dumps(detail, ensure_ascii=False)[:4000]
    target.updated_at = _now()
    if existing is None:
        db.add(target)
    await db.flush()
    await db.commit()
    record(
        "quality.score",
        {
            "tenant": tenant,
            "session_id": session_id,
            "score": target.score,
            "source": source,
            "assignee": target.assignee,
        },
    )
    return score_to_dict(target)


async def _judge(messages: list[dict[str, Any]], resolution: str) -> dict[str, Any] | None:
    """LLM-as-judge 一次调用；模型不可用返回 None 交给兜底（红线：绝不 500）。"""
    from app.services import llm_service

    transcript = build_transcript(messages, resolution)
    if not transcript:
        return None
    try:
        reply = await llm_service.complete(
            [
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
            max_tokens=300,
        )
    except llm_service.LlmUnavailableError:
        return None
    return parse_judge_output(reply.text)


async def auto_score_session(*, tenant: str, session_id: str) -> None:
    """resolve 后台自动评分入口（BackgroundTasks 用；自建会话，请求会话已关闭）。

    QUALITY_AUTO_SCORE=false 或已有人工评（source=manual）即跳过；任何异常只记
    可观测不外抛——评分失败不影响解决归档主流程。
    """
    if not settings.QUALITY_AUTO_SCORE:
        return
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_engine

    try:
        maker = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with maker() as db:
            current = (
                await db.execute(
                    select(SessionScore).where(
                        SessionScore.tenant == tenant, SessionScore.session_id == session_id
                    )
                )
            ).scalar_one_or_none()
            if current is not None and current.source == "manual":
                return
            await score_session(db, tenant=tenant, session_id=session_id)
    except Exception as exc:
        record(
            "quality.score", {"tenant": tenant, "session_id": session_id, "error": str(exc)[:200]}
        )


async def get_score(db: AsyncSession, *, tenant: str, session_id: str) -> dict[str, Any]:
    """读会话当前质检评分（未评返回 score=0 空形状，端点不 404）。"""
    await _session_row(db, tenant=tenant, session_id=session_id)
    row = (
        await db.execute(
            select(SessionScore).where(
                SessionScore.tenant == tenant, SessionScore.session_id == session_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {
            "id": "",
            "session_id": session_id,
            "assignee": "",
            "score": 0,
            "resolution_ok": False,
            "source": "",
            "reviewer": "",
            "detail": {},
            "pass": False,
            "updated_at": "",
        }
    return score_to_dict(row)


# ---------------- 绩效视图（GET /workbench/performance） ----------------


async def performance_view(db: AsyncSession, *, tenant: str) -> dict[str, Any]:
    """坐席绩效聚合：已解决会话数 / 质检均分 / 通过率 / 人工改评数（按 assignee）。

    口径：sessions.handoff_status=resolved 且 assignee 非空的行 join session_scores；
    未评分的解决会话计入 total 不计入均分；通过率分母=已评分会话。
    """
    pass_line = int(settings.QUALITY_PASS_SCORE)
    rows = list(
        (
            await db.execute(
                select(
                    Session.assignee,
                    func.count(),
                    func.avg(SessionScore.score),
                    func.sum(case((SessionScore.score >= pass_line, 1), else_=0)),
                    func.sum(case((SessionScore.source == "manual", 1), else_=0)),
                    func.sum(case((SessionScore.id.is_(None), 1), else_=0)),
                )
                .select_from(Session)
                .outerjoin(
                    SessionScore,
                    (SessionScore.session_id == Session.id)
                    & (SessionScore.tenant == Session.tenant),
                )
                .where(
                    Session.tenant == tenant,
                    Session.handoff_status == "resolved",
                    Session.assignee != "",
                )
                .group_by(Session.assignee)
                .order_by(Session.assignee)
            )
        ).all()
    )
    agents = []
    for assignee, total, avg, passed, manual, unscored in rows:
        scored = int(total) - int(unscored or 0)
        agents.append(
            {
                "assignee": str(assignee or ""),
                "resolved": int(total),
                "scored": scored,
                "avg_score": round(float(avg), 2) if avg is not None else None,
                "pass_rate": round(int(passed or 0) / scored, 4) if scored else None,
                "manual_reviews": int(manual or 0),
                "unscored": int(unscored or 0),
            }
        )
    return {
        "pass_score": pass_line,
        "auto_enabled": bool(settings.QUALITY_AUTO_SCORE),
        "agents": agents,
    }
