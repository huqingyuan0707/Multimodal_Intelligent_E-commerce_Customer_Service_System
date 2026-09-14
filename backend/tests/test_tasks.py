"""任务中心联调单测（建→跑→查闭环，对齐 API 规范 §4.5 + 页面设计 §3.3）

覆盖：直建演示任务后台跑完 done；reindex 走真实分块重建；
空类型 1001；跨租户 404；列表按本人隔离；端点 POST 分发后台执行。
运行（backend/ 目录）：pytest tests/test_tasks.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import ensure_kb_seed
from app.db.session import get_engine, init_models
from app.main import app
from app.services import task_service

TENANT = "tasks-tenant"
OTHER_TENANT = "tasks-other"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例夹具后还原；种子 29 篇供 reindex 真跑）。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tasks.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    monkeypatch.setattr(settings, "KB_SEED_DIR", str(ROOT / "docs" / "knowledge-base"))
    monkeypatch.setattr(settings, "SEED_TENANT", TENANT)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        assert await ensure_kb_seed(session) is True
        yield session


async def test_direct_demo_runs_to_done(db: AsyncSession) -> None:
    """演示任务：pending → running → done，进度 1.0 且落中文说明。"""
    row = await task_service.create_task(
        db, tenant=TENANT, username="demo", type="demo", payload={}
    )
    assert row.status == "pending"
    task_id = row.id
    await task_service.run_direct_task(tenant=TENANT, task_id=task_id, type="demo", payload={})
    db.expire_all()  # 后台跑在独立会话，本会话 identity map 需失效才读到新状态
    done = await task_service.get_task(db, tenant=TENANT, task_id=task_id)
    assert done.status == "done" and done.progress == 1.0


async def test_direct_reindex_rebuilds_for_real(db: AsyncSession) -> None:
    """reindex 直建任务：真实重建分块，产物含 docs/chunks。"""
    row = await task_service.create_task(
        db, tenant=TENANT, username="demo", type="reindex", payload={}
    )
    await task_service.run_direct_task(tenant=TENANT, task_id=row.id, type="reindex", payload={})
    task_id = row.id
    db.expire_all()  # 同上：独立会话写入后失效本地缓存（先存 id，过期后属性访问会懒加载）
    done = await task_service.get_task(db, tenant=TENANT, task_id=task_id)
    assert done.status == "done"
    assert task_service._parse_json(done.output, {})["docs"] >= 1


async def test_empty_type_rejected(db: AsyncSession) -> None:
    """空类型建任务：1001 中文可操作错误（端点直透，前端弹提示）。"""
    with pytest.raises(BusinessError) as exc:
        await task_service.create_task(db, tenant=TENANT, username="demo", type="  ", payload={})
    assert exc.value.code == ErrorCode.PARAM_INVALID


async def test_cross_tenant_get_404(db: AsyncSession) -> None:
    """跨租户单查：404 不泄露存在性。"""
    row = await task_service.create_task(
        db, tenant=TENANT, username="demo", type="demo", payload={}
    )
    with pytest.raises(BusinessError) as exc:
        await task_service.get_task(db, tenant=OTHER_TENANT, task_id=row.id)
    assert exc.value.code == ErrorCode.TASK_NOT_FOUND


async def test_list_isolated_to_user(db: AsyncSession) -> None:
    """列表按本人隔离：只能看到自己的任务。"""
    await task_service.create_task(db, tenant=TENANT, username="me", type="demo", payload={})
    await task_service.create_task(db, tenant=TENANT, username="other", type="demo", payload={})
    mine = await task_service.list_tasks(db, tenant=TENANT, username="me")
    assert len(mine) == 1


async def test_endpoint_dispatches_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点装配：POST /tasks 落库即返 task_id，后台跑完 GET 可见 done。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ep.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    tester = CurrentUser(username="tester", tenant=TENANT, roles=["*"])

    async def _override() -> CurrentUser:
        set_current_user(tester)
        return tester

    app.dependency_overrides[get_current_user] = _override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = (await client.post("/api/v1/tasks", json={"type": "demo"})).json()
            assert created["code"] == 0, created
            tid = created["data"]["task_id"]
            one = (await client.get(f"/api/v1/tasks/{tid}")).json()
            assert one["code"] == 0 and one["data"]["status"] == "done", one
    finally:
        app.dependency_overrides.clear()
