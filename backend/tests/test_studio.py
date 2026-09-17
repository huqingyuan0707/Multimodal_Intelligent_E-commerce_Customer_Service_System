"""Agent Studio 集成测试（Prompt 版本灰度回滚 + 评测一键跑，对齐 FRD FR-3/页面设计 §3.6）

链路：临时库（init_models 建表，不灌种子）+ 可切换鉴权 → Prompt 新建/列表分页/
     灰度发布/调灰/回滚/线上读取 → 评测建 run + 后台执行 + 详情轮询 →
     全量发布评测门禁（无 accept 即 1001）→ 对话链线上 prompt 接线回退口径。
覆盖红线：租户隔离（异租户 404/空列表）、买家 1003、版本号自动递增、单线上口径。
运行（backend/ 目录）：pytest tests/test_studio.py
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import EvalRun
from app.db.session import get_engine, init_models
from app.main import app
from app.services import studio_service
from app.services.chat_prompt import DEFAULT_SYSTEM_PROMPT, build_messages

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])
BUYER = CurrentUser(username="buyer1", tenant=TENANT, roles=[])
OTHER = CurrentUser(username="other", tenant="other-tenant", roles=["*"])

_current = {"user": TESTER}


async def _override() -> CurrentUser:
    """可切换鉴权：按用例在 tester/买家/异租户之间代入（ContextVar 同步写）。"""
    set_current_user(_current["user"])
    return _current["user"]


def login_as(user: CurrentUser) -> None:
    _current["user"] = user


async def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """独立临时库（只建表不灌种子：Prompt/评测用例不需要 29 篇种子知识）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'studio.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI 真调客户端（Studio 端点不依赖 Agent 注册中心）。"""
    await _prepare_db(tmp_path, monkeypatch)
    login_as(TESTER)
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def db_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncSession]:
    """同库直连会话（与 client 共享 tmp 库：伪造已达标评测行，测发布门禁正向路径）。"""
    await _prepare_db(tmp_path, monkeypatch)
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


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


async def _wait_eval_done(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """轮询评测 run 直到 done/failed（后台任务在传输内执行，超时即判失败）。"""
    for _ in range(100):
        data = await _ok(await client.get(f"/api/v1/studio/evals/{run_id}"))
        if data["status"] in ("done", "failed"):
            return data
        await asyncio.sleep(0.2)
    raise AssertionError(f"评测 run 长时间未结束：{run_id}")


async def test_prompt_lifecycle_gray_and_rollback(client: httpx.AsyncClient) -> None:
    """版本全流转：新建 v1/v2（自动递增）→ v1 进灰度 → 调灰 → v2 全量被评测门禁拦下 → 回滚 v1 上线。"""
    v1 = await _ok(
        await client.post(
            "/api/v1/studio/prompts", json={"desc": "首版", "content": "你是客服。{{city}}"}
        )
    )
    assert (v1["version"], v1["status"], v1["gray"]) == ("v1", "draft", 0)
    assert v1["variables"] == ["city"]
    v2 = await _ok(
        await client.post(
            "/api/v1/studio/prompts", json={"desc": "二版", "content": "你是资深客服。"}
        )
    )
    assert v2["version"] == "v2"

    gray = await _ok(await client.post("/api/v1/studio/prompts/v1/publish", json={"gray": 50}))
    assert (gray["status"], gray["gray"]) == ("gray", 50)
    tuned = await _ok(await client.post("/api/v1/studio/prompts/v1/gray", json={"gray": 80}))
    assert tuned["gray"] == 80

    # 全量发布无达标评测即 1001（前端红条与此同源）
    blocked = await _code(
        await client.post("/api/v1/studio/prompts/v2/publish", json={"gray": 100})
    )
    assert blocked["code"] == 1001

    rolled = await _ok(await client.post("/api/v1/studio/prompts/v1/rollback"))
    assert (rolled["status"], rolled["gray"]) == ("online", 100)
    online = await _ok(await client.get("/api/v1/studio/prompts/online"))
    assert online is not None and online["version"] == "v1"

    page = await _ok(await client.get("/api/v1/studio/prompts", params={"page": 1, "size": 1}))
    assert page["total"] == 2 and len(page["items"]) == 1 and page["size"] == 1


async def test_prompt_validation_and_perm(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """参数校验 + 权限 + 租户隔离：空正文/越界灰度/幽灵版本/买家/异租户。"""
    assert (await _code(await client.post("/api/v1/studio/prompts", json={"content": "   "})))[
        "code"
    ] == 1001
    assert (await _code(await client.post("/api/v1/studio/prompts/x9/publish", json={"gray": 10})))[
        "code"
    ] == 1004
    created = await _ok(
        await client.post("/api/v1/studio/prompts", json={"desc": "d", "content": "正文"})
    )
    assert (
        await _code(
            await client.post(
                f"/api/v1/studio/prompts/{created['version']}/publish", json={"gray": 101}
            )
        )
    )["code"] == 1001
    # draft 态不可调灰度（仅 gray 态可调）
    assert (
        await _code(
            await client.post(
                f"/api/v1/studio/prompts/{created['version']}/gray", json={"gray": 10}
            )
        )
    )["code"] == 1001

    login_as(BUYER)
    assert (await _code(await client.get("/api/v1/studio/prompts")))["code"] == 1003
    login_as(OTHER)
    # 异租户看不见本租户版本（列表空，不泄露存在性）
    assert (await _ok(await client.get("/api/v1/studio/prompts")))["total"] == 0
    login_as(TESTER)
    assert db_session is not None  # 同库直连夹具占位（本用例只走 HTTP，隔离由上面覆盖）


async def test_eval_run_end_to_end(client: httpx.AsyncClient) -> None:
    """评测一键跑：建 run 即返 → 轮询 done → 详情含双档 verdict + 分布 + 历史可见。"""
    created = await _ok(
        await client.post("/api/v1/studio/evals", json={"name": "default-200", "limit": 3})
    )
    assert created["status"] in ("pending", "running", "done")
    done = await _wait_eval_done(client, created["id"])
    assert done["status"] == "done", done
    score = done["score"]
    assert {"grounded", "hallucination", "per_scene", "guard_dist", "misses"} <= set(score)
    assert isinstance(done["pass"], bool) and isinstance(done["accept"], bool)
    assert done["elapsed_ms"] >= 0

    listed = await _ok(await client.get("/api/v1/studio/evals", params={"page": 1, "size": 20}))
    assert listed["total"] >= 1

    login_as(OTHER)
    assert (await _code(await client.get(f"/api/v1/studio/evals/{created['id']}")))["code"] == 1004
    login_as(TESTER)


async def test_publish_full_with_accept_eval(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """全量发布正向路径：伪造一次达验收线的 done 评测 → publish gray=100 上线。"""
    created = await _ok(
        await client.post(
            "/api/v1/studio/prompts", json={"desc": "待上线", "content": "你是客服。"}
        )
    )
    db_session.add(
        EvalRun(
            tenant=TENANT,
            name="default-200",
            limit=3,
            status="done",
            score=json.dumps(
                {
                    "grounded": 0.96,
                    "hallucination": 0.01,
                    "per_scene": {},
                    "guard_dist": {},
                    "misses": [],
                    "ratchet_ok": True,
                    "accept_ok": True,
                }
            ),
            created_by="tester",
        )
    )
    await db_session.commit()
    published = await _ok(
        await client.post(
            f"/api/v1/studio/prompts/{created['version']}/publish", json={"gray": 100}
        )
    )
    assert (published["status"], published["gray"]) == ("online", 100)


async def test_online_system_wiring() -> None:
    """对话链 prompt 接线口径：无版本回退空 + override 替换 system 位（纯函数不断言 DB）。"""
    assert DEFAULT_SYSTEM_PROMPT.strip() != ""
    msgs = build_messages("尺码怎么选", [], system_override="线上版：你是店小二。")
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == "线上版：你是店小二。"
    fallback = build_messages("尺码怎么选", [])
    assert fallback[0]["content"] == DEFAULT_SYSTEM_PROMPT


async def test_get_online_system_empty_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空租户无线上版本 → get_online_system 回空字符串（对话链走常量回退，不断言 DB 种子）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    from app.db import session as session_mod
    from app.db.session import get_engine, init_models

    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        assert await studio_service.get_online_system(db, tenant="ghost-tenant") == ""
