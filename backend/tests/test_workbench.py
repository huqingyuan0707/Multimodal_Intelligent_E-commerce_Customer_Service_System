"""坐席工作台集成测试（C 步转人工：队列/认领/转接/解决/备注/代回/Trace，对齐 FRD FR-7）

链路：ASGI 真调（临时库 + 种子 + 可切换鉴权）→ 买家建会话自助转人工 →
队列可见 → 抢接/转接/备注/代回/解决全流转 → 越权与租户隔离断言。
运行（backend/ 目录）：pytest tests/test_workbench.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app
from app.services import handoff_service, session_service, workbench_service

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])
BUYER = CurrentUser(username="buyer1", tenant=TENANT, roles=[])
CS2 = CurrentUser(username="cs2", tenant=TENANT, roles=["cs"])
OTHER = CurrentUser(username="other", tenant="other-tenant", roles=["cs"])

_current = {"user": TESTER}


async def _override() -> CurrentUser:
    """可切换鉴权：按用例在 tester/买家/坐席/异租户之间代入（ContextVar 同步写）。"""
    set_current_user(_current["user"])
    return _current["user"]


def login_as(user: CurrentUser) -> None:
    _current["user"] = user


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 可切换鉴权 ASGI 客户端。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'wb.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    login_as(TESTER)
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


async def _code(resp: httpx.Response) -> dict[str, Any]:
    """取业务信封（失败分支走 HTTP 4xx + code，同样断言 envelope 形状）。"""
    body = resp.json()
    assert "code" in body and "msg" in body, resp.text[:300]
    return body


async def _new_session(client: httpx.AsyncClient, title: str = "买家咨询") -> str:
    login_as(BUYER)
    data = await _ok(await client.post("/api/v1/sessions", json={"title": title}))
    return str(data["id"])


async def test_handoff_queue_claim_flow(client: httpx.AsyncClient) -> None:
    """主流程：买家转人工 → 队列可见 → 抢接 → 他人抢接被拦 → 转接 → 解决归档。"""
    sid = await _new_session(client)
    # 买家自助转人工（owner 口径，无 cs 角色也可）
    login_as(BUYER)
    handed = await _ok(
        await client.post(f"/api/v1/workbench/sessions/{sid}/handoff", json={"reason": "要人工"})
    )
    assert handed["handoff_status"] == "pending" and handed["handoff_label"] == "待接"
    # 队列可见（含中文标签 + 买家名 + 原因）
    login_as(TESTER)
    queue = await _ok(await client.get("/api/v1/workbench/queue"))
    assert queue["total"] == 1 and queue["items"][0]["username"] == "buyer1"
    assert queue["items"][0]["handoff_reason"] == "要人工"
    # 关键词与状态过滤
    assert (await _ok(await client.get("/api/v1/workbench/queue", params={"q": "咨询"})))[
        "total"
    ] == 1
    assert (await _ok(await client.get("/api/v1/workbench/queue", params={"q": "不存在"})))[
        "total"
    ] == 0
    assert (await _ok(await client.get("/api/v1/workbench/queue", params={"status": "resolved"})))[
        "total"
    ] == 0
    bad_status = await _code(await client.get("/api/v1/workbench/queue", params={"status": "xx"}))
    assert bad_status["code"] == 1001
    # 抢接
    claimed = await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))
    assert claimed["handoff_status"] == "handling" and claimed["assignee"] == "tester"
    # 他人抢接被拦（明示只读围观）
    login_as(CS2)
    conflict = await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))
    assert conflict["code"] == 1001 and "tester" in conflict["msg"]
    # 转接给 cs2
    login_as(TESTER)
    moved = await _ok(
        await client.post(f"/api/v1/workbench/sessions/{sid}/transfer", json={"assignee": "cs2"})
    )
    assert moved["assignee"] == "cs2" and moved["handoff_status"] == "handling"
    empty_transfer = await _code(
        await client.post(f"/api/v1/workbench/sessions/{sid}/transfer", json={"assignee": ""})
    )
    assert empty_transfer["code"] == 1001
    # 解决归档
    done = await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/resolve", json={"conclusion": "已退款"}
        )
    )
    assert done["handoff_status"] == "resolved" and done["resolution"] == "已退款"
    assert (await _ok(await client.get("/api/v1/workbench/queue")))["total"] == 0
    assert (await _ok(await client.get("/api/v1/workbench/queue", params={"status": "resolved"})))[
        "total"
    ] == 1
    # 重复解决 / 认领已解决均拦
    assert (await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/resolve")))[
        "code"
    ] == 1001
    assert (await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/claim")))[
        "code"
    ] == 1001
    # 解决后买家可再次转人工重开
    login_as(BUYER)
    reopened = await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/handoff"))
    assert reopened["handoff_status"] == "pending"


async def test_notes_reply_trace(client: httpx.AsyncClient) -> None:
    """备注 + 代回 + Trace：备注买家口无查询；代回落 agent 行；Trace 三段齐。"""
    sid = await _new_session(client, "售后破洞")
    login_as(BUYER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/handoff"))
    # 未认领代回被拦
    login_as(TESTER)
    assert (
        await _code(
            await client.post(f"/api/v1/workbench/sessions/{sid}/reply", json={"content": "你好"})
        )
    )["code"] == 1001
    assert (
        await _code(
            await client.post(f"/api/v1/workbench/sessions/{sid}/reply", json={"content": ""})
        )
    )["code"] == 1001
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))
    # 备注写读
    note = await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/notes", json={"content": "买家情绪稳定"}
        )
    )
    assert note["author"] == "tester" and note["content"] == "买家情绪稳定"
    assert (
        await _code(
            await client.post(f"/api/v1/workbench/sessions/{sid}/notes", json={"content": ""})
        )
    )["code"] == 1001
    notes = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid}/notes"))
    assert len(notes) == 1 and notes[0]["id"] == note["id"]
    # 代回落库
    msg = await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/reply", json={"content": "已安排换货，请留意短信"}
        )
    )
    assert msg["role"] == "agent" and "换货" in msg["content"] and msg["trace_id"]
    # Trace 三段齐（会话态 + 消息 + 上下文用量）
    trace = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid}/trace"))
    assert trace["session"]["handoff_status"] == "handling"
    assert any(m["id"] == msg["id"] for m in trace["messages"])
    assert {"rounds", "tokens", "budget"} <= set(trace["context"])


async def test_perm_and_isolation(client: httpx.AsyncClient) -> None:
    """权限与隔离：买家禁队列/备注/代回；异租户 404；幽灵会话 404。"""
    sid = await _new_session(client)
    login_as(BUYER)
    assert (await _code(await client.get("/api/v1/workbench/queue")))["code"] == 1003
    assert (await _code(await client.get(f"/api/v1/workbench/sessions/{sid}/notes")))[
        "code"
    ] == 1003
    assert (await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/claim")))[
        "code"
    ] == 1003
    # 买家只能转自己会话：幽灵 id 404
    assert (await _code(await client.post("/api/v1/workbench/sessions/ghost/handoff")))[
        "code"
    ] == 1004
    # 异租户坐席看不见本租户会话
    login_as(OTHER)
    assert (await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/claim")))[
        "code"
    ] == 1004
    assert (await _ok(await client.get("/api/v1/workbench/queue")))["total"] == 0


async def test_mark_pending_never_steals_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """自动挂起不抢单：none→pending；handling/resolved 原样不动（chat 钩子语义）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'hook.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    try:
        row = await session_service.create_session(
            db, tenant=TENANT, username="buyer1", title="钩子用例"
        )
        await handoff_service.mark_pending_if_idle(
            db, tenant=TENANT, session_id=row.id, reason="无据拒答，需人工确认"
        )
        assert row.handoff_status == "pending"
        row.handoff_status = "handling"
        row.assignee = "tester"
        await handoff_service.mark_pending_if_idle(
            db, tenant=TENANT, session_id=row.id, reason="VLM 低置信，需人工复核"
        )
        assert (row.handoff_status, row.assignee) == ("handling", "tester")
        row.handoff_status = "resolved"
        await handoff_service.mark_pending_if_idle(
            db, tenant=TENANT, session_id=row.id, reason="无据拒答，需人工确认"
        )
        assert row.handoff_status == "resolved"
    finally:
        await gen.aclose()


async def test_handoff_rules_endpoint(client: httpx.AsyncClient) -> None:
    """规则表端点：坐席可读规则清单 + 阈值；买家 1003（口径与 Settings 一致）。"""
    login_as(TESTER)
    data = await _ok(await client.get("/api/v1/workbench/handoff-rules"))
    assert data["enabled"] is True
    assert data["miss_streak_threshold"] == settings.HANDOFF_MISS_STREAK_THRESHOLD
    assert data["degrade_streak_threshold"] == settings.HANDOFF_DEGRADE_STREAK_THRESHOLD
    rules = {row["code"]: row for row in data["rules"]}
    assert {
        "explicit_request",
        "negative_sentiment",
        "sensitive_approval",
        "vision_low_confidence",
        "no_evidence",
        "miss_streak",
    } <= set(rules)
    assert rules["miss_streak"]["threshold"] == settings.HANDOFF_MISS_STREAK_THRESHOLD
    login_as(BUYER)
    assert (await _code(await client.get("/api/v1/workbench/handoff-rules")))["code"] == 1003


async def test_auto_handoff_follows_rule_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规则表挂载点：喊人工即挂起且文案来自规则表；已挂起不重复挂；handling 不抢；
    连续未解决到阈值才挂起；人工代回后连续计数清零。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rule.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    try:
        # 1) 买家喊人工 → explicit_request 命中并挂起（reason 直接用规则表文案）
        row = await session_service.create_session(
            db, tenant=TENANT, username="buyer1", title="规则挂载"
        )
        first = await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row.id, signals={"query": "我要转人工"}
        )
        assert (first["hit"], first["code"], first["applied"]) == (True, "explicit_request", True)
        assert row.handoff_status == "pending" and row.handoff_reason == first["reason"]
        # 2) 已 pending：仍命规则但不重复挂起，原因不被覆盖
        again = await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row.id, signals={"query": "转人工"}
        )
        assert (again["hit"], again["applied"], again["handoff_status"]) == (True, False, "pending")
        assert row.handoff_reason == first["reason"]
        # 3) 已认领：不抢单，状态与归属原样
        await workbench_service.claim(db, tenant=TENANT, user=TESTER, session_id=row.id)
        picked = await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row.id, signals={"no_evidence": True}
        )
        assert (picked["hit"], picked["applied"]) == (True, False)
        assert (row.handoff_status, row.assignee) == ("handling", "tester")

        # 4) 连续未解决：低于阈值不打扰人工，达阈值自动挂起
        row2 = await session_service.create_session(
            db, tenant=TENANT, username="buyer2", title="连续不懂"
        )
        threshold = settings.HANDOFF_MISS_STREAK_THRESHOLD
        for index in range(threshold):
            await session_service.save_agent_message(
                db,
                tenant=TENANT,
                session_id=row2.id,
                content="这条我暂时答不上来",
                citations=[],
                guard={"pass": True, "rejected": True},
                faithfulness=0.0,
                trace_id=f"trace-miss-{index}",
            )
            decision = await handoff_service.auto_handoff(db, tenant=TENANT, session_id=row2.id)
            if index < threshold - 1:
                assert decision["hit"] is False
            else:
                assert decision["code"] == "miss_streak"
        assert row2.handoff_status == "pending"

        # 5) 人工代回即清零：同样 2 轮未解决，中间夹一条坐席代回就不再累计到阈值
        row3 = await session_service.create_session(
            db, tenant=TENANT, username="buyer3", title="人工代回后"
        )
        for index, guard in enumerate(
            [
                {"pass": True, "rejected": True},
                {"pass": True, "by": "agent"},
                {"pass": True, "rejected": True},
                {"pass": True, "rejected": True},
            ]
        ):
            await session_service.save_agent_message(
                db,
                tenant=TENANT,
                session_id=row3.id,
                content="历史轮",
                citations=[],
                guard=guard,
                faithfulness=0.0,
                trace_id=f"trace-reset-{index}",
            )
        cleared = await handoff_service.auto_handoff(db, tenant=TENANT, session_id=row3.id)
        assert cleared["hit"] is False
        assert row3.handoff_status == "none"
    finally:
        await gen.aclose()
