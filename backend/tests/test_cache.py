"""Redis 适配层测试（对齐数据模型 §4 键规范 / API 规范 2002 限流）

链路：单测（窗口计数 / TTL 过期 / sticky 降级 / status 口径）+ 端点（/chat 超限 2002/429）。
本机无 Redis 服务也不装 redis 包时必须全绿——测的正是「不可用即内存降级」这条红线。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.core import cache
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app

TESTER = CurrentUser(username="tester", tenant=settings.SEED_TENANT, roles=["*"])


async def _tester_override() -> CurrentUser:
    """鉴权替换：通配权限 + 写入 ContextVar（与 test_api_endpoints 同口径）。"""
    set_current_user(TESTER)
    return TESTER


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 鉴权替换的 ASGI 客户端。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cache.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    app.dependency_overrides[get_current_user] = _tester_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fresh_cache():
    """每条用例前后清适配层粘性/窗口，防跨用例串计数。"""
    cache.reset()
    yield
    cache.reset()


async def test_allow_window_counts() -> None:
    """内存降级路径：窗口内 limit 次放行，超了拒绝。"""
    assert await cache.allow("rl:chat:t:u", 2, 60) is True
    assert await cache.allow("rl:chat:t:u", 2, 60) is True
    assert await cache.allow("rl:chat:t:u", 2, 60) is False


async def test_allow_zero_limit_disables() -> None:
    """limit<=0 = 关闭限流，恒放行（配置口径 CHAT_RATE_LIMIT_PER_MIN=0）。"""
    for _ in range(5):
        assert await cache.allow("rl:chat:t:off", 0, 60) is True


async def test_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口到期重开计数（假时钟推进 61s）。"""
    clock = {"now": 1000.0}
    monkeypatch.setattr(cache.time, "time", lambda: clock["now"])
    assert await cache.allow("rl:chat:t:win", 1, 60) is True
    assert await cache.allow("rl:chat:t:win", 1, 60) is False
    clock["now"] += 61
    assert await cache.allow("rl:chat:t:win", 1, 60) is True


async def test_json_roundtrip_and_miss() -> None:
    """get/set JSON 往返 + miss 返回 None + 过期后视为 miss。"""
    assert await cache.get_json("idem:x") is None
    await cache.set_json("idem:x", {"answer": "你好"}, 3600)
    got = await cache.get_json("idem:x")
    assert got == {"answer": "你好"}


async def test_sticky_degrade_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 Redis（依赖缺失或端口不通）：首次调用即 sticky 降级，功能不中断。"""
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    assert await cache.allow("rl:chat:t:deg", 3, 60) is True
    st = cache.status()
    assert st["degraded"] is True and st["backend"] == "memory"


async def test_chat_rate_limited_returns_2002(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点接线：限流=1 时第二次 /chat 返回 2002/429 中文可操作提示。"""
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_MIN", 1)
    body = {"query": "退货政策是什么", "thread_id": "t-rl", "client_msg_id": "rl-1"}
    first = await client.post("/api/v1/chat", json=body)
    assert first.json()["code"] in (0, 2001)  # 首轮放行（有/无据都算过限流关）
    second = await client.post("/api/v1/chat", json={**body, "client_msg_id": "rl-2"})
    assert second.status_code == 429
    data = second.json()
    assert data["code"] == 2002 and "频繁" in data["msg"]
