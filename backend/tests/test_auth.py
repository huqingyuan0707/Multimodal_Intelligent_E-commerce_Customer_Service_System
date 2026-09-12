"""认证与种子账号单测（对齐测试评估验收方案.md §2 单元测试）

覆盖：PBKDF2 验密与容错 / JWT 签发-解析-过期-篡改 / 建库后 authenticate 成功与失败 / 种子幂等。
运行（backend/ 目录）：pytest tests/test_auth.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, settings
from app.core.security import (
    decode_token,
    hash_password,
    issue_token,
    split_roles,
    verify_password,
)
from app.db import session as session_mod
from app.db.models import User
from app.db.seed import ensure_seed_user, seed_on_startup
from app.db.session import get_engine, init_models
from app.services import auth_service


def _seed_user() -> str:
    """种子账号取自 Settings，用例不写死账号（改配置无需改测试）。"""
    return settings.SEED_USERNAME


def _seed_pwd() -> str:
    return settings.SEED_PASSWORD.get_secret_value()


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库：重置引擎单例（monkeypatch 在用例结束后自动还原全局）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


def test_password_hash_roundtrip() -> None:
    stored = hash_password("demo1234")
    assert stored != "demo1234"
    assert verify_password("demo1234", stored)
    assert not verify_password("wrong", stored)


def test_verify_password_bad_format_returns_false() -> None:
    """落库格式非法（缺 salt 分隔符）不得抛异常，直接判失败。"""
    assert not verify_password("demo1234", "not-a-valid-hash")


def test_token_roundtrip_and_tamper() -> None:
    token = issue_token("demo", "demo-tenant", ["cs", "kb"])
    claims = decode_token(token)
    assert claims["sub"] == "demo"
    assert claims["tenant"] == "demo-tenant"
    assert claims["roles"] == ["cs", "kb"]
    with pytest.raises(ValueError):
        decode_token(f"{token}x")


def test_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """过期 Token 一律 ValueError（端点转 401），有效期走 Settings 不硬编码。"""
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_SECONDS", -1)
    with pytest.raises(ValueError, match="登录已过期"):
        decode_token(issue_token("demo", "demo-tenant", []))


async def test_authenticate_ok_and_fail(db: AsyncSession) -> None:
    assert await ensure_seed_user(db) is True
    user = await auth_service.authenticate(db, _seed_user(), _seed_pwd())
    assert user.username == _seed_user()
    assert user.tenant == settings.SEED_TENANT
    assert user.roles == settings.SEED_ROLES.split(",")
    assert auth_service.to_token(user)
    with pytest.raises(ValueError, match="用户名或密码错误"):
        await auth_service.authenticate(db, _seed_user(), "wrong")
    with pytest.raises(ValueError, match="用户名或密码错误"):
        await auth_service.authenticate(db, "ghost", _seed_pwd())


async def test_authenticate_trims_username(db: AsyncSession) -> None:
    """用户名首尾空格容错（前端输入框常见）。"""
    await ensure_seed_user(db)
    user = await auth_service.authenticate(db, f"  {_seed_user()}  ", _seed_pwd())
    assert user.username == _seed_user()


async def test_seed_user_idempotent(db: AsyncSession) -> None:
    """重复启动不重复建号，也不覆盖已改密码。"""
    assert await ensure_seed_user(db) is True
    assert await ensure_seed_user(db) is False
    total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    assert total == 1


async def test_seed_on_startup_uses_settings(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """lifespan 入口自建会话灌种子，账号取自 Settings。"""
    monkeypatch.setattr(settings, "SEED_USERNAME", "ops")
    monkeypatch.setattr(settings, "SEED_ROLES", "ops,admin")
    assert await seed_on_startup() is True
    user = await auth_service.authenticate(db, "ops", _seed_pwd())
    assert user.roles == ["ops", "admin"]


def test_split_roles_trims_and_drops_empty() -> None:
    """角色文本解析唯一口径（分隔符走 Settings，容忍空格与尾逗号）。"""
    assert split_roles("cs,kb") == ["cs", "kb"]
    assert split_roles(" cs , kb , ") == ["cs", "kb"]
    assert split_roles("") == []


def test_jwt_algorithm_follows_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """算法下沉 Settings：签发与校验同口径可往返。"""
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS512")
    claims = decode_token(issue_token("ops", "t1", ["cs"]))
    assert claims["sub"] == "ops"


def test_jwt_algorithm_mismatch_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """签发/校验算法不一致必须验签失败，暴露配置漂移而不是静默放行。"""
    token = issue_token("ops", "t1", [])
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS512")
    with pytest.raises(ValueError):
        decode_token(token)


def test_password_hash_iterations_follow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """迭代次数下沉 Settings：变更后存量哈希验不过（语义显式化，改配置须重刷密码）。"""
    stored = hash_password("pwd")
    monkeypatch.setattr(settings, "PASSWORD_HASH_ITERATIONS", 1000)
    assert hash_password("pwd") != stored
    assert not verify_password("pwd", stored)


def test_prod_env_rejects_default_jwt_secret() -> None:
    """生产护栏：ENV=prod 且沿用默认密钥 → 启动即失败，不带 demo 密钥上生产。"""
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(ENV="prod", JWT_SECRET="dev-only-change-me-and-rotate-in-prod")


def test_prod_env_rejects_seed_on_start() -> None:
    """生产护栏：ENV=prod 禁止自动灌种子账号。"""
    with pytest.raises(ValidationError, match="SEED_ON_START"):
        Settings(ENV="prod", JWT_SECRET="x" * 40, SEED_ON_START=True)


def test_prod_env_accepts_hardened_config() -> None:
    """合规的生产配置应正常构造。"""
    cfg = Settings(ENV="prod", JWT_SECRET="y" * 40, SEED_ON_START=False)
    assert cfg.ENV == "prod"
    assert cfg.SEED_ON_START is False
