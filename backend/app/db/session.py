"""异步 DB 会话（引擎单例 + 建表，对齐数据模型文档 §6 迁移节）

链路：init_models() 建表 → get_db() 取会话 → services 读写。
生产切 PG 只需换 DATABASE_URL，模型层无需改动。
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

_engine = None
_engine_lock = threading.Lock()
_SessionFactory: async_sessionmaker[AsyncSession] | None = None


def get_engine():  # type: ignore[no-untyped-def]
    """惰性单例引擎（双检锁，进程内唯一）。"""
    global _engine, _SessionFactory
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_async_engine(settings.DATABASE_URL, future=True)
                _SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)
    assert _SessionFactory is not None
    return _engine


async def init_models() -> None:
    """建表（幂等）。Alembic 接入后此处仅保留应急建表。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends 用的会话生成器（读写失败由调用方转 fail）。"""
    global _SessionFactory
    get_engine()
    assert _SessionFactory is not None
    async with _SessionFactory() as session:
        yield session
