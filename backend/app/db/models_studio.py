"""Agent Studio 模型（Prompt 版本灰度回滚 + 评测 runs，对齐 FRD FR-3/数据模型 §2）

链路：alembic 迁移建表 → studio_service 读写 → /studio 端点 →
      StudioView 三窗格（Prompt 版本/工具试调/评测跑分）。
口径：租户隔离（tenant 列）；Prompt 一租户同时只允许一个 online；
      灰度 0..100；评测 run 落 score JSON + 双档 verdict（棘轮/验收）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid


class PromptVersion(Base):
    """Prompt 版本（租户内 version 唯一；status: draft/gray/online/archived）。

    content 为 system prompt 全文；variables 为 {{var}} 变量名 JSON 数组（创建时自动提取）；
    gray 为灰度比例（online 恒 100）；回滚 = 指定版本重上 online，原 online 转 archived。
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("tenant", "version", name="uq_prompts_tenant_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    desc: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[str] = mapped_column(Text, default="[]")
    gray: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class EvalRun(Base):
    """评测 runs（黄金集一键跑：pending → running → done/failed，结果落 score JSON）。

    score 形状与 scripts/eval_golden._score 同口径并扩展：grounded/hallucination/
    per_scene/guard_dist/misses + ratchet_ok/accept_ok 双档 verdict；
    pass = ratchet_ok（与 CI RESULT 出口一致），全量发布门禁看 accept_ok。
    """

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), default="default-200")
    limit: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    score: Mapped[str] = mapped_column(Text, default="{}")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
