"""管理后台单测（租户/配额/审计，对齐 FRD FR-8 + 数据模型 §2）

红线口径逐一验证：
- 新建租户编码唯一，重复 1001；配额必须正数。
- 改配额/停服同步记审计；非法状态 1001。
- 改用户角色为空 1001；审计只追加（列表倒序可查）。
- 分页默认 20 口径（service 传 page/size，越权不涉及：仅 admin 可调由端点拦截）。
运行（backend/ 目录）：pytest tests/test_admin.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import User
from app.db.session import get_engine, init_models
from app.services import admin_service


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例夹具后还原）。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_create_and_quota_audit(db: AsyncSession) -> None:
    row = await admin_service.create_tenant(
        db,
        code="t-acme",
        name="Acme",
        plan="basic",
        actor="admin",
    )
    assert row.code == "t-acme"
    try:
        await admin_service.create_tenant(db, code="t-acme", name="重复", actor="admin")
        raise AssertionError("重复编码应抛错")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    updated = await admin_service.update_quota(
        db,
        code="t-acme",
        quota_tokens=5000,
        quota_concurrency=10,
        actor="admin",
    )
    assert updated.quota_tokens == 5000
    try:
        await admin_service.update_quota(
            db,
            code="t-acme",
            quota_tokens=0,
            quota_concurrency=1,
            actor="admin",
        )
        raise AssertionError("零配额应抛错")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    audits = await admin_service.list_audits(db, tenant="t-acme", page=1, size=20)
    actions = [a["action"] for a in audits["items"]]
    assert "tenant.create" in actions and "tenant.quota" in actions


async def test_status_and_roles(db: AsyncSession) -> None:
    await admin_service.create_tenant(db, code="t-s", name="S", actor="admin")
    suspended = await admin_service.set_status(
        db,
        code="t-s",
        status="suspended",
        actor="admin",
    )
    assert suspended.status == "suspended"
    try:
        await admin_service.set_status(db, code="t-s", status="unknown", actor="admin")
        raise AssertionError("非法状态应抛错")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    db.add(User(tenant="t-s", username="u1", pwd_hash="x", roles="cs"))
    await db.commit()
    users = await admin_service.list_users(db, tenant="t-s", page=1, size=20)
    assert users["total"] == 1
    uid = users["items"][0]["id"]
    changed = await admin_service.update_user_roles(
        db,
        user_id=uid,
        roles="cs,admin",
        actor="admin",
    )
    assert "admin" in changed.roles
    try:
        await admin_service.update_user_roles(db, user_id=uid, roles="  ", actor="admin")
        raise AssertionError("空角色应抛错")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    over = await admin_service.overview(db)
    assert over["tenant_total"] >= 1 and over["user_total"] >= 1
