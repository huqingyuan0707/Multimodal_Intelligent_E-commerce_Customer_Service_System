"""生产建号通道单测（对齐测试评估验收方案.md §2 单元测试）

覆盖：首建成功可登录 / 已存在幂等不动 / --reset 改密 / 弱口令与演示默认口令拒绝。
运行（backend/ 目录）：pytest tests/test_admin_bootstrap.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError
from app.db import session as session_mod
from app.db.session import get_engine, init_models
from app.services import auth_service
from app.services.admin_bootstrap import ensure_admin


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（与 test_auth.py 同口径，文件内自带，不跨文件复用）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_ensure_admin_creates_and_can_login(db: AsyncSession) -> None:
    """首建返回 created，且新口令可登录。"""
    assert await ensure_admin(db, tenant="acme", username="ops", password="AcmeOps-01") == "created"
    user = await auth_service.authenticate(db, "ops", "AcmeOps-01")
    assert user.tenant == "acme"
    assert "admin" in user.roles


async def test_ensure_admin_exists_without_reset_keeps_password(db: AsyncSession) -> None:
    """已存在且不带 reset：返回 exists，旧口令仍有效（不静默覆盖）。"""
    await ensure_admin(db, tenant="acme", username="ops", password="AcmeOps-01")
    assert (
        await ensure_admin(db, tenant="acme", username="ops", password="AcmeOps-02-new") == "exists"
    )
    await auth_service.authenticate(db, "ops", "AcmeOps-01")


async def test_ensure_admin_reset_rotates_password(db: AsyncSession) -> None:
    """带 reset：旧口令失效，新口令生效。"""
    await ensure_admin(db, tenant="acme", username="ops", password="AcmeOps-01")
    assert (
        await ensure_admin(
            db, tenant="acme", username="ops", password="AcmeOps-02-rotated", reset=True
        )
        == "reset"
    )
    await auth_service.authenticate(db, "ops", "AcmeOps-02-rotated")
    with pytest.raises(ValueError, match="用户名或密码错误"):
        await auth_service.authenticate(db, "ops", "AcmeOps-01")


async def test_ensure_admin_rejects_weak_and_demo_password(db: AsyncSession) -> None:
    """短口令与本地演示默认口令一律 1001 拒绝，禁止带上生产。"""
    with pytest.raises(BusinessError):
        await ensure_admin(db, tenant="acme", username="ops", password="short")
    with pytest.raises(BusinessError):
        await ensure_admin(db, tenant="acme", username="ops", password="admin123")
