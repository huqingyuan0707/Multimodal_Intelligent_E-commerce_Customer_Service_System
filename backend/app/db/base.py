"""ORM 基类与主键/时间口径（被 models 与 models_foundation 共享，对齐数据模型文档 §2）

链路：base.Base → 各模型 → session.init_models()/Alembic 建表。
SQLite 无原生 UUID，一律 String(32) hex；时间 naive UTC（与既有落库口径一致）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """声明式基类。"""


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    """naive UTC（保持既有落库口径）：datetime.utcnow() 在 3.12+ 已弃用，故显式转换。"""
    return datetime.now(UTC).replace(tzinfo=None)
