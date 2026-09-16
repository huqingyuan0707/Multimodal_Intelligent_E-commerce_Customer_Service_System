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
from sqlalchemy import select

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Session, User
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app
from app.services import handoff_routing, handoff_service, session_service, workbench_service

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


async def test_claim_race_only_one_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """抢接竞态：两个坐席各自会话同抢一条 pending——条件 UPDATE 保证只有一人赢，
    输家拿 1001「已被 X 接管」（旧实现读-改-写会互相覆盖 assignee）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    row = await session_service.create_session(
        db, tenant=TENANT, username="buyer1", title="抢接竞态"
    )
    await handoff_service.mark_pending_if_idle(db, tenant=TENANT, session_id=row.id, reason="排队")
    await db.commit()
    gen2 = session_mod.get_db()
    db2 = await gen2.__anext__()
    try:
        # 双方都先读到 pending（模拟并发窗口），再各自发起认领
        assert row.handoff_status == "pending"
        winner = await handoff_routing.claim(db, tenant=TENANT, user=TESTER, session_id=row.id)
        assert (winner.handoff_status, winner.assignee) == ("handling", "tester")
        with pytest.raises(BusinessError) as lost:
            await handoff_routing.claim(db2, tenant=TENANT, user=CS2, session_id=row.id)
        assert lost.value.code == ErrorCode.PARAM_INVALID
        assert "tester" in lost.value.msg
        # 输家重读：归属仍是赢家，没被覆盖
        check = (await db2.execute(select(Session).where(Session.id == row.id))).scalar_one()
        assert (check.handoff_status, check.assignee) == ("handling", "tester")
        # 赢家重复认领 = 幂等（不报错、归属不变）
        again = await handoff_routing.claim(db, tenant=TENANT, user=TESTER, session_id=row.id)
        assert again.assignee == "tester" and again.handoff_status == "handling"
    finally:
        await gen2.aclose()
        await gen.aclose()


async def test_skill_gate_and_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """技能组闭环：门禁（无组标坐席接不了专组单）+ 排队位（FIFO）+ 智能分配（最少负载优先）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'skill.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    try:
        db.add_all(
            [
                User(tenant=TENANT, username="cs_refund", pwd_hash="x", roles="cs,cs:refund"),
                User(tenant=TENANT, username="cs_general", pwd_hash="x", roles="cs"),
            ]
        )
        await db.commit()
        refund_user = CurrentUser(username="cs_refund", tenant=TENANT, roles=["cs", "cs:refund"])
        plain_user = CurrentUser(username="cs_general", tenant=TENANT, roles=["cs"])

        # 1) 退款组会话：无组标坐席 claim 被门禁（1001 明示缺组），组内坐席可接
        row = await session_service.create_session(db, tenant=TENANT, username="b1", title="退款单")
        await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row.id, signals={"approval_pending": True}
        )
        await db.commit()
        assert row.handoff_skill == "refund"
        with pytest.raises(BusinessError) as gate:
            await handoff_routing.claim(db, tenant=TENANT, user=plain_user, session_id=row.id)
        assert "退款售后" in gate.value.msg
        won = await handoff_routing.claim(db, tenant=TENANT, user=refund_user, session_id=row.id)
        assert (won.handoff_status, won.assignee) == ("handling", "cs_refund")

        # 2) 排队位：同组 pending 按等待时长 FIFO（先挂的排 1）
        first = await session_service.create_session(db, tenant=TENANT, username="b2", title="先挂")
        second = await session_service.create_session(
            db, tenant=TENANT, username="b3", title="后挂"
        )
        await handoff_service.mark_pending_if_idle(
            db, tenant=TENANT, session_id=first.id, reason="排队1", skill="general"
        )
        await db.commit()
        await handoff_service.mark_pending_if_idle(
            db, tenant=TENANT, session_id=second.id, reason="排队2", skill="general"
        )
        await db.commit()
        positions = await handoff_routing.pending_positions(db, tenant=TENANT, skill="general")
        assert (positions[first.id], positions[second.id]) == (1, 2)
        queued = await workbench_service.queue(db, tenant=TENANT, status="pending")
        by_id = {item["id"]: item for item in queued["items"]}
        assert by_id[first.id]["queue_position"] == 1
        assert by_id[first.id]["handoff_skill"] == "general"
        filtered = await workbench_service.queue(
            db, tenant=TENANT, status="pending", skill="refund"
        )
        assert all(item["handoff_skill"] == "refund" for item in filtered["items"])

        # 3) 智能分配：cs_refund 已在手 1 单，新退款单应派给更闲的组内坐席；无组标者不候选
        row2 = await session_service.create_session(
            db, tenant=TENANT, username="b4", title="退款单2"
        )
        await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row2.id, signals={"approval_pending": True}
        )
        await db.commit()
        assigned = await handoff_routing.assign(db, tenant=TENANT, user=TESTER, session_id=row2.id)
        assert (assigned.handoff_status, assigned.assignee) == ("handling", "cs_refund")
        # 满载即拒：上限压到 1，cs_refund 在手 2 单 → 无候选，1001 明示满载，会话留队列
        monkeypatch.setattr(settings, "HANDOFF_LOAD_LIMIT", 1)
        row3 = await session_service.create_session(
            db, tenant=TENANT, username="b5", title="退款单3"
        )
        await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row3.id, signals={"approval_pending": True}
        )
        await db.commit()
        with pytest.raises(BusinessError) as full:
            await handoff_routing.assign(db, tenant=TENANT, user=TESTER, session_id=row3.id)
        assert "满载" in full.value.msg
        assert row3.handoff_status == "pending"
        # 关闭分配：上限 0 → 1001 提示手动抢接
        monkeypatch.setattr(settings, "HANDOFF_LOAD_LIMIT", 0)
        with pytest.raises(BusinessError) as off:
            await handoff_routing.assign(db, tenant=TENANT, user=TESTER, session_id=row3.id)
        assert "已关闭" in off.value.msg

        # 4) 负载视图：坐席在手数 + 各组待接数
        monkeypatch.setattr(settings, "HANDOFF_LOAD_LIMIT", 5)
        view = await handoff_routing.load_view(db, tenant=TENANT)
        loads = {a["username"]: a["handling"] for a in view["agents"]}
        assert loads["cs_refund"] == 2 and loads["cs_general"] == 0
        assert view["pending_by_skill"]["refund"] == 1
        assert {g["key"] for g in view["skill_groups"]} >= {"general", "refund"}
    finally:
        await gen.aclose()


async def test_metrics_endpoint(client: httpx.AsyncClient) -> None:
    """运营指标口：坐席可读（接起率形状 + 队列存量实况）；买家 1003。"""
    login_as(TESTER)
    data = await _ok(await client.get("/api/v1/workbench/metrics"))
    obs = data["observability"]
    handoff = obs["handoff"]
    assert {"hits", "applied", "claims", "answer_rate", "target_seconds"} <= set(handoff)
    assert handoff["target_seconds"] == settings.OBSERVABILITY_ANSWER_TARGET_SECONDS
    assert set(data["queue"]) == {"none", "pending", "handling", "resolved"}
    # 认领一次 → 进程内计数即时反映（handoff.claim ≥1）
    created = await _ok(await client.post("/api/v1/sessions", json={"title": "指标用例"}))
    sid = created["id"]
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/handoff", json={}))
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))
    after = await _ok(await client.get("/api/v1/workbench/metrics"))
    assert after["observability"]["handoff"]["claims"] >= 1
    assert after["queue"]["handling"] >= 1
    login_as(BUYER)
    assert (await _code(await client.get("/api/v1/workbench/metrics")))["code"] == 1003


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
        assert row.handoff_skill == "general"  # 喊人工路由通用组
        # 1b) 退款送审路由退款组（技能组隔离：队列筛选/认领门禁/分配按组走）
        row_ref = await session_service.create_session(
            db, tenant=TENANT, username="buyer1", title="退款路由"
        )
        routed = await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row_ref.id, signals={"approval_pending": True}
        )
        assert routed["skill"] == "refund" and row_ref.handoff_skill == "refund"
        # 2) 已 pending：仍命规则但不重复挂起，原因不被覆盖
        again = await handoff_service.auto_handoff(
            db, tenant=TENANT, session_id=row.id, signals={"query": "转人工"}
        )
        assert (again["hit"], again["applied"], again["handoff_status"]) == (True, False, "pending")
        assert row.handoff_reason == first["reason"]
        # 3) 已认领：不抢单，状态与归属原样
        await handoff_routing.claim(db, tenant=TENANT, user=TESTER, session_id=row.id)
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


async def test_quality_score_rule_manual_performance(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """质检闭环（C 步收官）：resolve 后台自动评分（LLM 关走规则兜底）→ 查分 →
    人工改评覆盖 → 越界拦截 → 绩效聚合（含未评会话）；异租户/幽灵会话 404。"""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)  # 不依赖 Ollama：judge 直接走规则兜底
    sid = await _new_session(client, "退货咨询")
    login_as(BUYER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/handoff"))
    login_as(TESTER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))
    # 未评：score=0 空形状（端点不 404）
    empty = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid}/score"))
    assert empty["score"] == 0 and empty["source"] == ""
    # 代回 + 解决 → 后台自动评分（ASGITransport 下 background 同步跑完）
    await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/reply", json={"content": "已为您办理退货"}
        )
    )
    await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/resolve", json={"conclusion": "退货已受理"}
        )
    )
    scored = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid}/score"))
    assert scored["source"] == "rule" and scored["assignee"] == "tester"
    assert scored["score"] == 5  # 基线3 + 有客服回复 +1 + 有解决小结 +1
    assert scored["resolution_ok"] is True and scored["pass"] is True
    # 人工改评覆盖（source=manual + reviewer 留痕）
    manual = await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid}/score",
            json={"score": 2, "resolution_ok": False, "comment": "回复模板化，未确认运单"},
        )
    )
    assert manual["source"] == "manual" and manual["reviewer"] == "tester"
    assert manual["score"] == 2 and manual["pass"] is False
    # 越界/非法分数 1001
    for bad in ({"score": 0}, {"score": 6}, {"score": "x"}):
        assert (
            await _code(await client.post(f"/api/v1/workbench/sessions/{sid}/score", json=bad))
        )["code"] == 1001
    # 未评会话（关自动评分）→ 绩效 unscored 计数
    monkeypatch.setattr(settings, "QUALITY_AUTO_SCORE", False)
    sid2 = await _new_session(client, "物流催单")
    login_as(BUYER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid2}/handoff"))
    login_as(TESTER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid2}/claim"))
    await _ok(
        await client.post(
            f"/api/v1/workbench/sessions/{sid2}/resolve", json={"conclusion": "已催单"}
        )
    )
    perf = await _ok(await client.get("/api/v1/workbench/performance"))
    assert perf["pass_score"] == int(settings.QUALITY_PASS_SCORE)
    assert perf["auto_enabled"] is False
    row = next(a for a in perf["agents"] if a["assignee"] == "tester")
    assert row["resolved"] == 2 and row["scored"] == 1 and row["unscored"] == 1
    assert row["avg_score"] == 2.0 and row["pass_rate"] == 0.0 and row["manual_reviews"] == 1
    # 隔离：异租户查分 404；幽灵会话 404
    login_as(OTHER)
    assert (await _code(await client.get(f"/api/v1/workbench/sessions/{sid}/score")))[
        "code"
    ] == 1004
    login_as(TESTER)
    assert (await _code(await client.get("/api/v1/workbench/sessions/nope/score")))[
        "code"
    ] == 1004


async def test_quality_judge_paths(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM-as-judge 双路径：输出可解析落 judge 分；模型不可用降级规则兜底（绝不 500）。"""
    from types import SimpleNamespace

    from app.services import llm_service, quality_service

    # 纯函数：合法 JSON 解析（未知维度丢弃）；坏输出/越界一律 None
    good = quality_service.parse_judge_output(
        '{"score": 4, "resolution_ok": true, "dimensions": {"resolution": 4, "bogus": 9},'
        ' "reason": "基本解决"}'
    )
    assert good is not None and good["score"] == 4 and good["dimensions"] == {"resolution": 4}
    assert quality_service.parse_judge_output("抱歉，我无法输出 JSON") is None
    assert quality_service.parse_judge_output('{"score": 9, "resolution_ok": true}') is None

    sid = await _new_session(client, "换货咨询")
    login_as(BUYER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/handoff"))
    login_as(TESTER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid}/claim"))

    async def _fake_ok(messages: list[dict[str, str]], **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            text='{"score": 5, "resolution_ok": true, "dimensions": {}, "reason": "全部解决"}'
        )

    monkeypatch.setattr(llm_service, "complete", _fake_ok)
    await _ok(
        await client.post(f"/api/v1/workbench/sessions/{sid}/resolve", json={"conclusion": "已换货"})
    )
    judged = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid}/score"))
    assert judged["source"] == "judge" and judged["score"] == 5
    assert judged["detail"]["reason"] == "全部解决"

    # 模型不可用 → 规则兜底（source=rule），resolve 主流程不受影响
    sid2 = await _new_session(client, "发票咨询")
    login_as(BUYER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid2}/handoff"))
    login_as(TESTER)
    await _ok(await client.post(f"/api/v1/workbench/sessions/{sid2}/claim"))

    async def _fake_down(messages: list[dict[str, str]], **_: object) -> SimpleNamespace:
        raise llm_service.LlmUnavailableError("模型离线")

    monkeypatch.setattr(llm_service, "complete", _fake_down)
    await _ok(
        await client.post(f"/api/v1/workbench/sessions/{sid2}/resolve", json={"conclusion": "已开票"})
    )
    ruled = await _ok(await client.get(f"/api/v1/workbench/sessions/{sid2}/score"))
    assert ruled["source"] == "rule" and 1 <= ruled["score"] <= 5
