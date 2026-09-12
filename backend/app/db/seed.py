"""种子账号（首次启动幂等灌入，对齐数据模型与存储设计.md §6 迁移节）

链路：main.lifespan（SEED_ON_START）/ scripts/init_db.py → ensure_seed_user() → 无则建账号。
租户/用户名/密码/角色一律走 Settings（.env 可覆盖），禁止硬编码；生产置 SEED_ON_START=false。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_engine


async def ensure_seed_user(db: AsyncSession) -> bool:
    """幂等灌种子：已存在返回 False，新建返回 True（重复启动不覆盖已改密码）。"""
    tenant = settings.SEED_TENANT
    username = settings.SEED_USERNAME
    exists = (
        await db.execute(select(User).where(User.tenant == tenant, User.username == username))
    ).scalar_one_or_none()
    if exists is not None:
        return False
    db.add(
        User(
            tenant=tenant,
            username=username,
            pwd_hash=hash_password(settings.SEED_PASSWORD.get_secret_value()),
            roles=settings.SEED_ROLES,
        )
    )
    await db.commit()
    return True


async def seed_on_startup() -> bool:
    """lifespan 调用入口：自建会话灌种子（调用前须已 init_models 建表）。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        return await ensure_seed_user(db)
