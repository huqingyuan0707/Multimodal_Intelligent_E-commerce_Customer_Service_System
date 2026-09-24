"""Agent Runtime 集成测试（B 步：状态机 / 工具注册中心 / 策略 / 执行器 / 检查点，对齐 FRD-3/FR-5）

链路：临时库 + 全量种子 + 可切换鉴权 → 注册中心清单 → 受控试调（Scope/审批/熔断/超时重试）
      → 退款恒送审（账不动 → 审批通过 → 才生效）→ 编排 /agent/run 落检查点 → resume 续跑。
覆盖红线：越权 403、跨租户 404、非幂等不重试、业务拒绝不计熔断、审批未决不放行续跑。
运行（backend/ 目录）：pytest tests/test_agent_runtime.py
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Task, ToolCall
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app
from app.modules.agent import connectors, executor, policy, registry, runtime
from app.modules.agent.contracts import ToolContext, ToolSpec, validate_args
from app.services import llm_service, order_service

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])
BUYER = CurrentUser(username="buyer1", tenant=TENANT, roles=[])
CS = CurrentUser(username="cs1", tenant=TENANT, roles=["cs", "order:read", "kb:read"])
OTHER = CurrentUser(username="other", tenant="other-tenant", roles=["*"])

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
_current = {"user": TESTER}


async def _override() -> CurrentUser:
    """可切换鉴权：按用例在 tester/买家/客服/异租户之间代入（ContextVar 同步写）。"""
    set_current_user(_current["user"])
    return _current["user"]


def login_as(user: CurrentUser) -> None:
    _current["user"] = user


async def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """独立临时库 + 全量种子（每个用例一个库，互不串数据）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI 真调客户端（先在 lifespan 外注册工具，等价于启动期 bootstrap）。"""
    await _prepare_db(tmp_path, monkeypatch)
    connectors.register_all()
    executor.reset_breakers()
    login_as(TESTER)
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """裸会话（执行器单测用：审计写库与熔断状态需要真表）。"""
    await _prepare_db(tmp_path, monkeypatch)
    connectors.register_all()
    executor.reset_breakers()
    gen = session_mod.get_db()
    session = await gen.__anext__()
    try:
        yield session
    finally:
        await gen.aclose()


async def _ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text[:400]
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


async def _code(resp: httpx.Response) -> dict[str, Any]:
    """取失败信封（HTTP 4xx + code，同样断言 envelope 形状）。"""
    body = resp.json()
    assert "code" in body and "msg" in body, resp.text[:400]
    return body


async def _ctx(db: Any, user: CurrentUser = TESTER) -> ToolContext:
    return ToolContext(
        db=db,
        tenant=user.tenant,
        username=user.username,
        roles=list(user.roles),
        trace_id="t-trace",
    )


async def _shipped_order(client: httpx.AsyncClient) -> str:
    """取一张「已发货」演示订单（可发起售后，且带面单可取物流）。"""
    login_as(TESTER)
    data = await _ok(await client.get("/api/v1/orders", params={"status": "shipped", "size": 20}))
    assert data["items"], "种子数据缺少已发货订单，无法验证退款与物流链路"
    return str(data["items"][0]["id"])


# ---------------- 注册中心与契约 ----------------


async def test_registry_specs_align_frd() -> None:
    """注册中心：6 个连接器齐、Scope 与附录 A 一致、超时重试口径落 Settings、退款恒送审。"""
    connectors.register_all()
    assert registry.names() == [
        "coupon.query",
        "kb.retrieve",
        "logistics.query",
        "order.query",
        "refund.create",
        "stock.query",
        "ticket.create",
    ]
    assert connectors.self_check() == []
    scopes = {spec.name: spec.scope for spec in registry.all_specs()}
    assert scopes == {
        "order.query": "order:read",
        "logistics.query": "order:read",
        "stock.query": "stock:read",
        "coupon.query": "promo:read",
        "kb.retrieve": "kb:read",
        "refund.create": "trade:refund",
        "ticket.create": "ticket:write",
    }
    refund = registry.get("refund.create")
    assert refund.requires_approval is True and refund.approval_action == "order.refund"
    assert refund.idempotent is False, "资金类工具绝不能自动重试"
    view = registry.spec_to_dict(refund)
    assert view["timeout_seconds"] == settings.AGENT_TOOL_TIMEOUT_SECONDS
    assert view["max_retries"] == 0, "非幂等工具生效重试次数必须为 0"
    assert registry.spec_to_dict(registry.get("order.query"))["max_retries"] == (
        settings.AGENT_TOOL_MAX_RETRIES
    )
    # 幂等注册：重复装载不报错也不重复计数（启动重放安全）
    connectors.register_all()
    assert registry.count() == 7
    with pytest.raises(BusinessError) as err:
        registry.get("nope.tool")
    assert err.value.code == ErrorCode.TOOL_NOT_FOUND


async def test_schema_validation() -> None:
    """JSON Schema 子集校验：必填/类型/枚举/边界/additionalProperties 全中文可读。"""
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "title": "金额", "minimum": 1},
            "reason": {"type": "string", "title": "原因", "maxLength": 4},
            "level": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["amount"],
        "additionalProperties": False,
    }
    assert validate_args(schema, {"amount": 1}) == []
    assert "缺少必填参数「金额」" in validate_args(schema, {})[0]
    assert "应为整数" in validate_args(schema, {"amount": True})[0], "布尔值不得被当成整数"
    assert "不得小于 1" in validate_args(schema, {"amount": 0})[0]
    assert "最长 4 个字符" in validate_args(schema, {"amount": 1, "reason": "这个原因太长了"})[0]
    assert "只能是 a/b" in validate_args(schema, {"amount": 1, "level": "c"})[0]
    assert "不支持的参数" in validate_args(schema, {"amount": 1, "extra": 1})[0]
    # 真实连接器：退款入参不齐必须被拦在调用之前
    refund = registry.get("refund.create")
    assert validate_args(refund.params, {"order_id": "x", "amount": 100}) != []


async def test_policy_scope_and_approval() -> None:
    """策略：Scope 不命中直接拒（含通配与多角色），敏感工具恒判送审。"""
    refund = registry.get("refund.create")
    buyer = policy.check(roles=BUYER.roles, spec=refund, args={})
    assert buyer["allowed"] is False and "trade:refund" in buyer["reason"]
    cs = policy.check(roles=CS.roles, spec=refund, args={})
    assert cs["allowed"] is False, "客服无 trade:refund 时也不得放行退款"
    assert policy.check(roles=["*"], spec=refund, args={})["approval_required"] is True
    assert policy.check(roles=["order:read"], spec=registry.get("order.query"), args={}) == {
        "allowed": True,
        "approval_required": False,
        "scope": "order:read",
        "reason": "",
    }
    with pytest.raises(BusinessError) as err:
        policy.ensure_allowed(roles=BUYER.roles, spec=registry.get("order.query"), args={})
    assert err.value.code == ErrorCode.TOOL_SCOPE_DENIED and err.value.http_status == 403


# ---------------- 执行器：超时 / 重试 / 熔断 ----------------


async def test_executor_timeout_and_retry(db: Any) -> None:
    """超时按 TOOL_CALL_FAILED 抛中文错；幂等工具退避重试到成功并记真实尝试次数。"""
    calls = {"n": 0}

    async def _slow(_ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.5)
        return {"ok": True}

    async def _flaky(_ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("依赖抖动")
        return {"ok": True, "n": calls["n"]}

    registry.register(
        ToolSpec(
            name="t.slow",
            scope="order:read",
            description="超时用例",
            params=_EMPTY_SCHEMA,
            handler=_slow,
            timeout_seconds=0.05,
            max_retries=0,
        )
    )
    registry.register(
        ToolSpec(
            name="t.flaky",
            scope="order:read",
            description="重试用例",
            params=_EMPTY_SCHEMA,
            handler=_flaky,
            timeout_seconds=2.0,
            max_retries=3,
        )
    )
    try:
        ctx = await _ctx(db)
        with pytest.raises(BusinessError) as err:
            await executor.call(ctx, name="t.slow")
        assert err.value.code == ErrorCode.TASK_TIMEOUT and "超时" in err.value.msg
        got = await executor.call(ctx, name="t.flaky")
        assert got["status"] == "ok" and got["attempts"] == 3 and calls["n"] == 3
        rows = (await db.execute(select(func.count()).select_from(ToolCall))).scalar_one()
        assert rows >= 2, "成功与失败都必须落 tool_calls 审计"
    finally:
        registry.unregister("t.slow")
        registry.unregister("t.flaky")
        executor.reset_breakers()


async def test_executor_circuit_breaker(db: Any) -> None:
    """熔断：连续失败达阈值即开闸，后续调用快速失败 4007；复位后可再调。"""

    async def _boom(_ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("供应商挂了")

    registry.register(
        ToolSpec(
            name="t.boom",
            scope="order:read",
            description="熔断用例",
            params=_EMPTY_SCHEMA,
            handler=_boom,
            timeout_seconds=1.0,
            max_retries=0,
        )
    )
    try:
        ctx = await _ctx(db)
        for _ in range(int(settings.AGENT_TOOL_CIRCUIT_THRESHOLD)):
            with pytest.raises(BusinessError) as err:
                await executor.call(ctx, name="t.boom")
            assert err.value.code == ErrorCode.TOOL_CALL_FAILED
        snap = executor.breaker_snapshot("t.boom")
        assert snap["open"] is True and snap["failures"] >= settings.AGENT_TOOL_CIRCUIT_THRESHOLD
        with pytest.raises(BusinessError) as opened:
            await executor.call(ctx, name="t.boom")
        assert opened.value.code == ErrorCode.TOOL_CIRCUIT_OPEN
        executor.reset_breakers("t.boom")
        assert executor.breaker_snapshot("t.boom")["open"] is False
    finally:
        registry.unregister("t.boom")
        executor.reset_breakers()


async def test_executor_business_error_not_retried(db: Any) -> None:
    """业务拒绝（如订单不存在）：不重试、不计熔断，原码上抛（避免把正常拒绝当故障）。"""
    calls = {"n": 0}

    async def _reject(_ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        raise BusinessError(ErrorCode.ORDER_NOT_FOUND, "订单不存在或无权访问", 404)

    registry.register(
        ToolSpec(
            name="t.reject",
            scope="order:read",
            description="业务拒绝用例",
            params=_EMPTY_SCHEMA,
            handler=_reject,
            max_retries=3,
        )
    )
    try:
        ctx = await _ctx(db)
        with pytest.raises(BusinessError) as err:
            await executor.call(ctx, name="t.reject")
        assert err.value.code == ErrorCode.ORDER_NOT_FOUND
        assert calls["n"] == 1, "业务拒绝不得触发重试"
        assert executor.breaker_snapshot("t.reject")["failures"] == 0, "业务拒绝不得计入熔断"
    finally:
        registry.unregister("t.reject")
        executor.reset_breakers()


# ---------------- 端点：注册中心 / 受控试调 / 越权隔离 ----------------


async def test_agent_tools_endpoints(client: httpx.AsyncClient) -> None:
    """注册中心端点：清单带 Scope/Schema/超时重试/熔断态；未注册工具 4005。"""
    data = await _ok(await client.get("/api/v1/agent/tools"))
    assert data["total"] == 7
    by_name = {item["name"]: item for item in data["items"]}
    assert by_name["refund.create"]["requires_approval"] is True
    assert by_name["refund.create"]["breaker"]["open"] is False
    assert by_name["kb.retrieve"]["params"]["required"] == ["query"]
    single = await _ok(await client.get("/api/v1/agent/tools/order.query"))
    assert single["scope"] == "order:read"
    assert "handler" not in single, "注册中心出参绝不能把可调用对象透给前端"
    missing = await _code(await client.get("/api/v1/agent/tools/ghost.tool"))
    assert missing["code"] == 4005


async def test_refund_tool_always_approval(client: httpx.AsyncClient) -> None:
    """退款恒送审：低于阈值也进审批，调用后账不动；审批通过才落售后（FR-7 / 附录 A）。"""
    order_id = await _shipped_order(client)
    payload = {
        "args": {"order_id": order_id, "amount": 5000, "reason": "袖口脱线 2cm"},
        "trace_id": "t-refund",
    }
    data = await _ok(await client.post("/api/v1/agent/tools/refund.create/invoke", json=payload))
    assert data["approval_required"] is True and data["approval_id"], "AI 发起的退款必须落审批单"
    assert data["result"]["need_approval"] is True, "低于阈值的 AI 退款也必须送审"
    detail = await _ok(await client.get(f"/api/v1/orders/{order_id}"))
    assert detail["status"] == "shipped", "审批未过，订单状态绝不能先动"
    pending = await _ok(
        await client.get("/api/v1/approvals", params={"status": "pending", "page": 1, "size": 20})
    )
    ids = [row["id"] for row in pending["items"]]
    assert data["approval_id"] in ids
    approved = await _ok(
        await client.post(
            f"/api/v1/approvals/{data['approval_id']}/approve", json={"reason": "同意退款"}
        )
    )
    assert approved["status"] == "approved"
    after = await _ok(await client.get(f"/api/v1/orders/{order_id}"))
    assert after["status"] == "aftersale", "审批通过后应由 apply_refund 生效"


async def test_agent_perm_and_isolation(client: httpx.AsyncClient) -> None:
    """越权与隔离：无 Scope 调工具 403/4006；异租户查编排快照 404；缺参数 1001。"""
    order_id = await _shipped_order(client)
    login_as(BUYER)
    denied = await _code(
        await client.post(
            "/api/v1/agent/tools/order.query/invoke", json={"args": {"order_id": order_id}}
        )
    )
    assert denied["code"] == 4006, "买家无 order:read，工具调用必须被策略拦下"
    assert (await _ok(await client.get("/api/v1/agent/tools")))["total"] == 7, (
        "清单只读，登录即可见"
    )
    # 参数校验在策略之后：换成有 order:read 的客服，才能走到 1001 分支
    login_as(CS)
    bad_args = await _code(
        await client.post("/api/v1/agent/tools/order.query/invoke", json={"args": {}})
    )
    assert bad_args["code"] == 1001
    login_as(TESTER)
    run = await _ok(
        await client.post(
            "/api/v1/agent/run",
            json={"query": "我的订单发货了吗", "tool_args": {"order_id": order_id}},
        )
    )
    login_as(OTHER)
    ghost = await _code(await client.get(f"/api/v1/agent/runtime/{run['task_id']}"))
    assert ghost["code"] == 4001, "跨租户查编排快照必须 404（不泄露存在性）"


# ---------------- 编排：状态机 / 检查点 / 恢复 ----------------


async def test_runtime_run_done_and_checkpoint(client: httpx.AsyncClient) -> None:
    """编排走通：规则规划命中物流 → 执行 → DONE，检查点落 tasks 表且工具审计留痕。"""
    order_id = await _shipped_order(client)
    data = await _ok(
        await client.post(
            "/api/v1/agent/run",
            json={
                "query": "我的快递到哪了",
                "session_id": "",
                "tool_args": {"order_id": order_id},
                "trace_id": "t-run",
            },
        )
    )
    assert data["state"] == "DONE" and data["state_label"] == "已完成"
    assert data["steps"][0]["tool"] == "logistics.query"
    assert data["results"][0]["status"] == "ok"
    assert "物流" in data["answer"]
    snap = await _ok(await client.get(f"/api/v1/agent/runtime/{data['task_id']}"))
    assert snap["state"] == "DONE" and snap["cursor"] == 1 and snap["updated_at"]
    unknown = await _code(await client.get("/api/v1/agent/runtime/ghost-task"))
    assert unknown["code"] == 4001


async def test_runtime_missing_params_falls_back_to_kb(client: httpx.AsyncClient) -> None:
    """规划兜底：命中「退款」但没给订单号 → 不硬调，回落知识库并说明原因。"""
    data = await _ok(await client.post("/api/v1/agent/run", json={"query": "我要退款怎么办"}))
    assert data["steps"][0]["tool"] == "kb.retrieve", "缺参时绝不带残参硬调敏感工具"
    assert any("缺少必填参数" in note for note in data["notes"])
    assert data["state"] in {"DONE", "WAITING_HUMAN"}


async def test_runtime_approval_gate_and_resume(client: httpx.AsyncClient) -> None:
    """审批分支：退款编排挂起 WAITING_APPROVAL；未批续跑 4003；批后续跑收敛 DONE。"""
    order_id = await _shipped_order(client)
    run = await _ok(
        await client.post(
            "/api/v1/agent/run",
            json={
                "query": "衣服破了要退款",
                "tool_args": {"order_id": order_id, "amount": 5000, "reason": "袖口脱线"},
            },
        )
    )
    assert run["state"] == "WAITING_APPROVAL" and run["approval_id"]
    blocked = await _code(await client.post(f"/api/v1/agent/runtime/{run['task_id']}/resume"))
    assert blocked["code"] == 4003, "审批未决不得绕过人工放行续跑"
    await _ok(
        await client.post(
            f"/api/v1/approvals/{run['approval_id']}/approve", json={"reason": "同意"}
        )
    )
    resumed = await _ok(await client.post(f"/api/v1/agent/runtime/{run['task_id']}/resume"))
    assert resumed["state"] == "DONE"
    assert (await _ok(await client.get(f"/api/v1/orders/{order_id}")))["status"] == "aftersale"


async def test_runtime_waiting_human_when_no_evidence(client: httpx.AsyncClient) -> None:
    """无据分支：知识库零召回 → WAITING_HUMAN（不编造答案），并把会话挂进待接队列。"""
    login_as(BUYER)
    session = await _ok(await client.post("/api/v1/sessions", json={"title": "无据兜底用例"}))
    login_as(TESTER)
    run = await _ok(
        await client.post(
            "/api/v1/agent/run",
            json={"query": "zzzzqqq 完全无关的问题 xxxx", "session_id": session["id"]},
        )
    )
    assert run["state"] == "WAITING_HUMAN" and run["state_label"] == "等待人工"
    assert "转人工" in run["answer"] or any("转人工" in n for n in run["notes"])
    queue = await _ok(await client.get("/api/v1/workbench/queue"))
    assert any(row["id"] == session["id"] for row in queue["items"]), "无据必须自动挂起待接队列"


# ---------------- 对话主链：检索段走编排（执行步骤 B 余项①接线） ----------------

_KB_HIT = "退货政策是什么"


def _offline_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型离线（确定性）：只验编排接线与帧形，不依赖本机 Ollama。"""

    async def _no_complete(_messages: list[dict[str, str]]) -> object:
        raise llm_service.LlmUnavailableError("单测：模型离线")

    async def _no_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        raise llm_service.LlmUnavailableError("单测：模型离线")
        yield ""  # pragma: no cover - 仅为让桩函数是 async generator

    monkeypatch.setattr(llm_service, "complete", _no_complete)
    monkeypatch.setattr(llm_service, "acomplete_stream", _no_stream)


async def _done_payload(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    """跑一次 /agent/chat/stream 并取 done 帧载荷（顺带断言 source 起、done 收）。"""
    async with client.stream("POST", "/api/v1/agent/chat/stream", json=body) as resp:
        assert resp.status_code == 200, resp.text[:200]
        lines = [line async for line in resp.aiter_lines()]
    events = [line.removeprefix("event: ") for line in lines if line.startswith("event: ")]
    assert events and events[0] == "source" and events[-1] == "done", events
    payload = next(
        (
            lines[index + 1].removeprefix("data: ")
            for index, line in enumerate(lines)
            if line == "event: done"
        ),
        "",
    )
    assert payload, "done 帧必须带 data"
    return json.loads(payload)


async def test_chat_main_chain_orchestrates_kb_retrieve(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主链接线：编排规划出 kb.retrieve 并真调连接器，非流式与 done 帧都透出 tool_calls。"""
    _offline_llm(monkeypatch)
    login_as(TESTER)
    data = await _ok(await client.post("/api/v1/agent/chat", json={"query": _KB_HIT}))
    assert [call["tool"] for call in data["tool_calls"]] == ["kb.retrieve"], (
        "检索段必须走工具执行器"
    )
    call = data["tool_calls"][0]
    assert call["status"] == "ok" and call["scope"] == "kb:read"
    assert call["trace_id"] == data["trace_id"], "工具审计与回答必须同一 trace_id 可回查"
    assert data["orchestration"] == {"notes": []}
    assert data["references"], "工具结果要回喂检索口径，引用不能因改走编排而丢"
    done = await _done_payload(client, {"query": _KB_HIT, "client_msg_id": "orch-sse-1"})
    assert [c["tool"] for c in done["tool_calls"]] == ["kb.retrieve"]
    assert done["orchestration"]["notes"] == [] and done["references"]


async def test_chat_orchestration_notes_are_honest(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命中「退款」却缺订单号：绝不自动生成资金审批单，编排说明如实透出。"""
    _offline_llm(monkeypatch)
    login_as(TESTER)
    data = await _ok(await client.post("/api/v1/agent/chat", json={"query": "退款时效是多久"}))
    assert any("缺少必填参数" in note for note in data["orchestration"]["notes"])
    assert [call["tool"] for call in data["tool_calls"]] == ["kb.retrieve"], "缺参不得带残参硬调"
    assert data["references"]
    pending = await _ok(
        await client.get("/api/v1/approvals", params={"status": "pending", "page": 1, "size": 20})
    )
    assert all(row["action"] != "order.refund" for row in pending["items"]), (
        "对话主链不得替买家自动发起退款审批"
    )


async def test_chat_orchestration_switch_and_kernel_fallback(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一键回退与内核未装载两条路都回落直连检索：引用照旧、绝不 500、绝不 2001 拒答。"""
    _offline_llm(monkeypatch)
    login_as(TESTER)
    monkeypatch.setattr(settings, "AGENT_CHAT_ORCHESTRATE", False)
    off = await _ok(await client.post("/api/v1/agent/chat", json={"query": _KB_HIT}))
    assert off["references"] and off["tool_calls"] == []
    assert off["orchestration"] == {"notes": ["编排不可用，已回落直连检索"]}
    monkeypatch.setattr(settings, "AGENT_CHAT_ORCHESTRATE", True)
    monkeypatch.setattr(registry, "maybe_get", lambda _name: None)
    bare = await _ok(await client.post("/api/v1/agent/chat", json={"query": _KB_HIT}))
    assert bare["references"] and bare["tool_calls"] == []
    assert bare["orchestration"]["notes"] == ["编排不可用，已回落直连检索"]


async def test_orchestrate_business_fact_without_task_row(db: Any) -> None:
    """编排入口：给全主键才真调业务工具，事实拼进 tool_block；对话轮次绝不建 tasks 行。"""
    set_current_user(TESTER)
    orders = await order_service.list_orders(db, tenant=TENANT, status="shipped", size=1)
    assert orders["items"], "种子缺少已发货订单，无法验证业务事实注入"
    data = await runtime.orchestrate(
        db,
        user=TESTER,
        query="我的快递到哪了",
        tool_args={"order_id": str(orders["items"][0]["id"])},
        trace_id="t-orch",
    )
    assert data is not None, "内核已装载时必须给出编排结果"
    assert [call["tool"] for call in data["tool_calls"]] == ["logistics.query"]
    assert "物流" in data["tool_block"], "业务事实必须拼给模型，否则等于白调"
    assert data["refs"] == [], "引用只由 kb.retrieve 提供"
    assert data["empty"] is False and data["approval"] == {}
    tasks = (await db.execute(select(func.count()).select_from(Task))).scalar_one()
    assert tasks == 0, "对话主链不建 tasks 行（否则每条买家消息都刷任务中心）"
    audits = (await db.execute(select(func.count()).select_from(ToolCall))).scalar_one()
    assert audits >= 1, "编排调用同样要落 tool_calls 审计"
