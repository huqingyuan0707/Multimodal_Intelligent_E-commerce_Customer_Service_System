"""联动模式②（office-agent 回流写单）集成测试：网关建单 / 幂等回放 / Scope 拦截

链路：临时库 + 种子 → POST /agent-gateway/invoke ticket.create（带 idem_key）
      → 首单落库 replayed=False → 同键重放返回原单 replayed=True（绝不双单）
      → 缺幂等键 1001 → 有入口令牌但无 ticket:write 4006。
口径：审批闸门唯一在对端（office-agent），本侧网关直接执行；幂等键是「重放不双单」的唯一防线。
运行（backend/ 目录）：pytest tests/test_linkage_writeback.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Ticket
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app
from app.modules.agent import connectors, executor

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])
# 只持入口令牌、不持写 Scope 的服务账号（验证工具级 Scope 硬拦）
SVC_NO_WRITE = CurrentUser(username="svc-office-agent", tenant=TENANT, roles=["svc", "agent:gateway"])

_current: dict[str, CurrentUser] = {"user": TESTER}


async def _override() -> CurrentUser:
    set_current_user(_current["user"])
    return _current["user"]


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 种子 + 连接器注册（等价启动期 bootstrap）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'link.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    connectors.register_all()
    executor.reset_breakers()
    _current["user"] = TESTER
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _invoke(client: httpx.AsyncClient, args: dict[str, Any]) -> httpx.Response:
    return await client.post(
        "/api/v1/agent-gateway/invoke",
        json={"tool": "ticket.create", "args": args},
    )


async def test_gateway_ticket_create_and_idempotent_replay(client: httpx.AsyncClient) -> None:
    """首单生效 + 同键重放返回原单：跨系统「审批重放不双单」的落点。"""
    args = {
        "kind": "office-callback",
        "source_ref": "run-20260924-001",
        "assignee": "cs1",
        "sla_hours": 24,
        "idem_key": "idem-linkage-0001",
    }
    first = (await _invoke(client, args)).json()
    assert first["code"] == 0, first
    data1 = first["data"]
    assert data1["status"] == "ok"
    assert data1["result"]["replayed"] is False
    assert data1["result"]["ticket_id"]

    second = (await _invoke(client, args)).json()
    assert second["code"] == 0, second
    data2 = second["data"]
    assert data2["result"]["replayed"] is True
    assert data2["result"]["ticket_id"] == data1["result"]["ticket_id"]

    # 直查库：同键有且只有一单
    factory = session_mod._SessionFactory
    assert factory is not None
    async with factory() as db:
        count = (
            await db.execute(
                select(func.count()).select_from(Ticket).where(Ticket.idem_key == args["idem_key"])
            )
        ).scalar_one()
    assert count == 1


async def test_gateway_ticket_create_requires_idem_key(client: httpx.AsyncClient) -> None:
    """缺幂等键：Schema 校验 1001 拒单（写动作恒带键，没有「裸写」通道）。"""
    body = (await _invoke(client, {"kind": "office-callback"})).json()
    assert body["code"] == 1001
    assert "缺少必填参数" in body["msg"] and "幂等键" in body["msg"]


async def test_gateway_ticket_create_scope_denied(client: httpx.AsyncClient) -> None:
    """有入口令牌但无 ticket:write：工具 Scope 硬拦 4006（最小权限口径）。"""
    _current["user"] = SVC_NO_WRITE
    try:
        body = (
            await _invoke(
                client,
                {"kind": "office-callback", "idem_key": "idem-linkage-0002"},
            )
        ).json()
    finally:
        _current["user"] = TESTER
    assert body["code"] == 4006, body
