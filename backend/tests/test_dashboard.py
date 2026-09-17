"""数据看板汇总测试（GET /observability/summary 真实聚合，对齐 API 规范 §4.6）

链路：ASGI 真调（临时库 + 种子 + 可切换鉴权）→ 买家建会话/插消息/工具调用 →
admin 看全租户汇总（指标 6 项 + 今日 24 桶趋势 + 慢 Trace + 归因分页）→ 越权/非法参数分支。
运行（backend/ 目录）：pytest tests/test_dashboard.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Session
from app.db.models_foundation import Message, ToolCall
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app

TENANT = settings.SEED_TENANT
ADMIN = CurrentUser(username="boss", tenant=TENANT, roles=["admin"])
BUYER = CurrentUser(username="buyer1", tenant=TENANT, roles=[])

_current = {"user": ADMIN}


async def _override() -> CurrentUser:
    """可切换鉴权（admin 看全租户，买家应 403）。"""
    set_current_user(_current["user"])
    return _current["user"]


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 可切换鉴权 ASGI 客户端（同 test_workbench 口径）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'db.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    _current["user"] = ADMIN
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


async def _seed_chat() -> None:
    """2 会话（1 转人工）+ 3 用户消息（成本 120 分）+ 2 工具调用（900/150ms）。"""
    assert session_mod._SessionFactory is not None
    async with session_mod._SessionFactory() as db:
        db.add(Session(id="s-a", tenant=TENANT, username="buyer1", handoff_status="pending"))
        db.add(Session(id="s-b", tenant=TENANT, username="buyer1", handoff_status="none"))
        # created_at 显式用本地时间（与 dashboard_service._trend 的 datetime.now() 同基准）：
        # 落库默认是 naive UTC（models_foundation/base._now），本地凌晨时 UTC 仍在昨天，
        # 会被 today 的 day_start 过滤导致 24 桶全空（时序敏感，白天跑才会绿）。
        local_now = datetime.now()
        db.add(
            Message(
                session_id="s-a", tenant=TENANT, role="user", content="问价", created_at=local_now
            )
        )
        db.add(
            Message(
                session_id="s-a", tenant=TENANT, role="user", content="问尺码", created_at=local_now
            )
        )
        db.add(
            Message(
                session_id="s-a",
                tenant=TENANT,
                role="user",
                content="问发货",
                cost_cents=120,
                created_at=local_now,
            )
        )
        db.add(Message(session_id="s-a", tenant=TENANT, role="agent", content="答"))
        db.add(ToolCall(trace_id="slow-trace-1", tenant=TENANT, name="kb.retrieve", latency_ms=900))
        db.add(ToolCall(trace_id="fast-trace-2", tenant=TENANT, name="order.query", latency_ms=150))
        await db.commit()


async def test_summary_shape_and_math(client: httpx.AsyncClient) -> None:
    """汇总形状 + 真实聚合数学（解决率 50% + 成本 ¥1.20 + 慢 Trace 排序 + 24 桶）。"""
    await _seed_chat()
    data = await _ok(await client.get("/api/v1/observability/summary"))
    assert [m["key"] for m in data["metrics"]] == [
        "qps",
        "p95",
        "resolve",
        "hallucination",
        "tool",
        "cost",
    ]
    by_key = {m["key"]: m for m in data["metrics"]}
    assert by_key["resolve"]["value"] == "50.0%"
    assert by_key["cost"]["value"] == "¥1.20"
    assert by_key["p95"]["value"] == "—" and by_key["hallucination"]["value"] == "—"
    assert len(data["trend"]) == 24
    assert sum(p["value"] for p in data["trend"]) == 3
    assert [t["trace_id"] for t in data["slow_traces"]] == ["slow-trace-1", "fast-trace-2"]
    assert data["slow_traces"][0]["latency_ms"] == 900
    assert data["total"] == 1 and data["page"] == 1 and data["range"] == "today"
    row = data["items"][0]
    assert row["tenant"] == TENANT and row["sessions"] == 2
    assert row["resolveRate"] == "50.0%" and row["costCents"] == 120
    assert row["slowTraceId"] == "slow-trace-1" and row["overBudget"] is False


async def test_summary_week_and_paging(client: httpx.AsyncClient) -> None:
    """近 7 日 7 桶 + 分页越界回空列表（total 照实）。"""
    await _seed_chat()
    week = await _ok(await client.get("/api/v1/observability/summary", params={"range": "week"}))
    assert len(week["trend"]) == 7 and week["range"] == "week"
    assert sum(p["value"] for p in week["trend"]) == 3
    empty = await _ok(
        await client.get("/api/v1/observability/summary", params={"page": 9, "size": 20})
    )
    assert empty["items"] == [] and empty["total"] == 1


async def test_summary_guards(client: httpx.AsyncClient) -> None:
    """买家 403 + 非法 range 1001（与审批 status 非法同口径）。"""
    _current["user"] = BUYER
    denied = await client.get("/api/v1/observability/summary")
    assert denied.status_code == 403
    _current["user"] = ADMIN
    bad = await client.get("/api/v1/observability/summary", params={"range": "month"})
    assert bad.status_code == 400
    assert bad.json()["code"] == 1001
