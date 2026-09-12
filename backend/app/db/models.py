"""ORM 模型（最小 P0 集，对齐数据模型文档 §2）

链路：session.create_tables 建表 → services 读写 → scripts/init_db.py 灌种子用户。
SQLite 无原生 UUID/数组类型，一律用 String/JSON 文本，PG 迁移时再收紧。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """声明式基类。"""


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    """naive UTC（保持既有落库口径）：datetime.utcnow() 在 3.12+ 已弃用，故显式转换。"""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    """登录用户（租户内用户名唯一，角色逗号分隔存文本）。"""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant", "username", name="uq_users_tenant_username"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    pwd_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    roles: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Session(Base):
    """会话（P0 仅落盘标题与归属，消息持久化后续补）。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    created_at: Mapped[datetime] = mapped_column(default=_now)
