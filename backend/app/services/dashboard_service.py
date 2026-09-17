"""数据看板汇总（运营视角真实聚合，对齐 API 规范 §4.6 + 页面设计 §3.7）

链路：GET /observability/summary → dashboard_service.summary →
sessions/messages/tool_calls 聚合 + observability.snapshot()。
口径（无运行时数据的指标一律回 '—' 不编数，desc 写明出处）：
- 问答 QPS：近 5 分钟用户消息数 /300；问答轮次：用户消息总数
- 自动解决率：未进转人工会话占比（handoff_status=='none' / 全部会话）
- 首字 P95 / 幻觉率：运行时无采集 → '—'（压测/黄金集离线口径）
- 工具成功率：observability agent.tool.ok 占比（无调用 → '—'）
- Token 成本：messages.cost_cents 求和（costing 单实现按 Settings 单价折算；
  人工对照 + 估算单占比见成本卡 desc）
- 趋势：今日 24 小时桶 / 近 7 日按天桶（用户消息数，DB created_at 分桶）
- 归因：按租户（admin 看全租户，否则本租户）+ 服务端分页
- 慢 Trace：tool_calls 按 latency_ms 倒序 Top5（trace_id + 耗时 + 工具名）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import snapshot as obs_snapshot
from app.core.user_context import CurrentUser
from app.db.models import CostRecord, Session
from app.db.models_foundation import Message, ToolCall
from app.services import costing

_TREND_TODAY_BUCKETS = 24
_TREND_WEEK_DAYS = 7
_QPS_WINDOW_SECONDS = 300


def _pct(top: float, total: float) -> str:
    """占比转一位小数百分比字符串（分母为 0 回 '—' 不编数）。"""
    return f"{top / total * 100:.1f}%" if total else "—"


async def _tenant_list(db: AsyncSession, user: CurrentUser) -> list[str]:
    """可见租户：admin 看全租户（sessions 去重），否则只看本租户。"""
    if "admin" in user.roles or "*" in user.roles:
        rows = (await db.execute(select(Session.tenant).distinct().order_by(Session.tenant))).all()
        tenants = [str(r[0]) for r in rows if r[0]]
        return tenants or [user.tenant]
    return [user.tenant]


async def summary(
    db: AsyncSession,
    *,
    user: CurrentUser,
    page: int = 1,
    size: int = 20,
    range_: str = "today",
) -> dict[str, Any]:
    """看板汇总（range_ 仅 today|week，非法由端点层 1001 拦截）。"""
    now = datetime.now()
    tenants = await _tenant_list(db, user)
    in_scope = Message.tenant.in_(tenants)

    total_sessions = int(
        (
            await db.execute(
                select(func.count()).select_from(Session).where(Session.tenant.in_(tenants))
            )
        ).scalar_one()
    )
    applied = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Session)
                .where(Session.tenant.in_(tenants), Session.handoff_status != "none")
            )
        ).scalar_one()
    )
    turns = int(
        (
            await db.execute(
                select(func.count()).select_from(Message).where(in_scope, Message.role == "user")
            )
        ).scalar_one()
    )
    recent = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    in_scope,
                    Message.role == "user",
                    Message.created_at >= now - timedelta(seconds=_QPS_WINDOW_SECONDS),
                )
            )
        ).scalar_one()
    )
    cost_cents = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Message.cost_cents), 0))
                .select_from(Message)
                .where(in_scope)
            )
        ).scalar_one()
    )
    est_cents = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(CostRecord.cost_cents), 0))
                .select_from(CostRecord)
                .where(
                    CostRecord.tenant.in_(tenants),
                    CostRecord.pricing_source == "estimate",
                )
            )
        ).scalar_one()
    )
    all_cents = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(CostRecord.cost_cents), 0))
                .select_from(CostRecord)
                .where(CostRecord.tenant.in_(tenants))
            )
        ).scalar_one()
    )
    snap = obs_snapshot()
    tool_rate = snap.get("tool_ok_rate")
    answer_rate = snap.get("handoff", {}).get("answer_rate")
    human_yuan = settings.HUMAN_COST_PER_TICKET_CENTS / 100
    human_ratio = costing.vs_human_ratio(cost_cents)
    human_text = f"{human_ratio}%" if human_ratio is not None else "—"
    est_text = f"{est_cents / all_cents * 100:.0f}%" if all_cents else "—"
    answer_text = f"{answer_rate * 100:.1f}%" if answer_rate is not None else "—"

    metrics = [
        {
            "key": "qps",
            "label": "问答 QPS",
            "value": f"{recent / _QPS_WINDOW_SECONDS:.1f}",
            "desc": f"近 5 分钟用户消息数/300（问答轮次累计 {turns}）",
            "overBudget": False,
        },
        {
            "key": "p95",
            "label": "首字 P95",
            "value": "—",
            "desc": "流式首字分位统计未接（压测见执行步骤〇节），不编数",
            "overBudget": False,
        },
        {
            "key": "resolve",
            "label": "自动解决率",
            "value": _pct(total_sessions - applied, total_sessions),
            "desc": f"未进转人工会话占比（30s 接起率 {answer_text}）",
            "overBudget": False,
        },
        {
            "key": "hallucination",
            "label": "幻觉率",
            "value": "—",
            "desc": "离线黄金集评估口径（目标 ≤2%），运行时不编数",
            "overBudget": False,
        },
        {
            "key": "tool",
            "label": "工具成功率",
            "value": f"{tool_rate * 100:.1f}%" if tool_rate is not None else "—",
            "desc": "业务连接器调用成功占比（无调用时为 —）",
            "overBudget": False,
        },
        {
            "key": "cost",
            "label": "Token 成本",
            "value": f"¥{cost_cents / 100:.2f}",
            "desc": f"messages.cost_cents 求和（单价 Settings 可热更；约为人工 ¥{human_yuan:.2f}/通的 {human_text}；估算单占比 {est_text}，越低越准）",
            "overBudget": False,
        },
    ]

    trend = await _trend(db, tenants=tenants, now=now, range_=range_)
    slow = await _slow_traces(db, tenants=tenants, limit=5)
    items = await _attribution(db, tenants=tenants)
    total = len(items)
    start = (page - 1) * size
    return {
        "metrics": metrics,
        "trend": trend,
        "slow_traces": slow,
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "size": size,
        "range": range_,
    }


async def _trend(
    db: AsyncSession, *, tenants: list[str], now: datetime, range_: str
) -> list[dict[str, Any]]:
    """趋势序列：today=今日 24 小时桶，week=近 7 日按天桶（用户消息数）。"""
    if range_ == "week":
        days = [(now - timedelta(days=i)).date() for i in range(_TREND_WEEK_DAYS - 1, -1, -1)]
        start = datetime(days[0].year, days[0].month, days[0].day)
        labels = [d.strftime("%m-%d") for d in days]
        keys = [d.isoformat() for d in days]

        def key_of(ts: datetime) -> str:
            return ts.date().isoformat()
    else:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day_start
        labels = [f"{h:02d}时" for h in range(_TREND_TODAY_BUCKETS)]
        keys = [str(h) for h in range(_TREND_TODAY_BUCKETS)]

        def key_of(ts: datetime) -> str:
            return str(ts.hour)

    rows = (
        await db.execute(
            select(Message.created_at)
            .where(
                Message.tenant.in_(tenants),
                Message.role == "user",
                Message.created_at >= start,
            )
            .order_by(Message.created_at)
        )
    ).all()
    counts: dict[str, int] = dict.fromkeys(keys, 0)
    for (ts,) in rows:
        if ts is None:
            continue
        key = key_of(ts)
        if key in counts:
            counts[key] += 1
    return [{"label": label, "value": counts[key]} for label, key in zip(labels, keys, strict=True)]


async def _slow_traces(db: AsyncSession, *, tenants: list[str], limit: int) -> list[dict[str, Any]]:
    """慢 Trace（tool_calls 按 latency_ms 倒序，无耗时记录时回空列表不伪造）。"""
    rows = (
        await db.execute(
            select(ToolCall.trace_id, ToolCall.latency_ms, ToolCall.name)
            .where(ToolCall.tenant.in_(tenants), ToolCall.latency_ms > 0)
            .order_by(ToolCall.latency_ms.desc())
            .limit(limit)
        )
    ).all()
    return [{"trace_id": trace or "—", "latency_ms": ms, "tool": name} for trace, ms, name in rows]


async def _attribution(db: AsyncSession, *, tenants: list[str]) -> list[dict[str, Any]]:
    """按租户归因行（渠道列 DB 无口径回 '—'；单租户最慢 tool trace 透出，无则 '—'）。"""
    items = []
    for tenant in tenants:
        sessions = int(
            (
                await db.execute(
                    select(func.count()).select_from(Session).where(Session.tenant == tenant)
                )
            ).scalar_one()
        )
        applied = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Session)
                    .where(Session.tenant == tenant, Session.handoff_status != "none")
                )
            ).scalar_one()
        )
        cost = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Message.cost_cents), 0))
                    .select_from(Message)
                    .where(Message.tenant == tenant)
                )
            ).scalar_one()
        )
        slowest = (
            await db.execute(
                select(ToolCall.trace_id)
                .where(ToolCall.tenant == tenant, ToolCall.latency_ms > 0)
                .order_by(ToolCall.latency_ms.desc())
                .limit(1)
            )
        ).first()
        items.append(
            {
                "id": f"a-{tenant}",
                "tenant": tenant,
                "channel": "—",
                "sessions": sessions,
                "resolveRate": _pct(sessions - applied, sessions),
                "costCents": cost,
                "overBudget": False,
                "slowTraceId": (slowest[0] if slowest and slowest[0] else "—"),
            }
        )
    return items
