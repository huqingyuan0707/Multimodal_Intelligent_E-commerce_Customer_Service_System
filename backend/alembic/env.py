"""Alembic 同步迁移环境（前置地基，对齐数据模型文档 §6）

链路：alembic upgrade head → 本文件读 Settings.DATABASE_URL（async 转 sync）
→ Base.metadata 全量建表。业务代码不直连具体库，迁移脚本与 PG/SQLite 同源。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 全量模型注册（缺一即漏表）：models 重导出地基表，foundation 必须显式 import。
import app.db.models
import app.db.models_foundation  # noqa: F401
from app.config import settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url(async_url: str) -> str:
    """async 驱动转同步迁移驱动：aiosqlite→sqlite，asyncpg→psycopg2。"""
    url = async_url.replace("sqlite+aiosqlite://", "sqlite://")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(settings.DATABASE_URL), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
