"""质检评分模型（C 步收官：会话质检打分，对齐 FRD FR-7「质检打分」+ 数据模型 §2）

链路：坐席 resolve 会话 → 后台 LLM-as-judge 自动评分（模型不可用走规则兜底）
      → 本表落一行（一会话一行，重评覆盖）→ 坐席可在绩效面板人工改评 →
      GET /workbench/sessions/{id}/score / GET /workbench/performance 读取。
口径：score 1..5 综合分；detail 存各维分与依据 JSON（judge 原文截断留证）；
     source=judge（模型评）/ rule（兜底评）/ manual（人工改评），审计可回溯谁评的。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid


class SessionScore(Base):
    """会话质检评分（租户隔离；一会话一行，重评原地覆盖，留 updated_at 轨迹）。"""

    __tablename__ = "session_scores"
    __table_args__ = (UniqueConstraint("tenant", "session_id", name="uq_scores_tenant_session"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    assignee: Mapped[str] = mapped_column(String(64), default="", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)  # 综合 1..5；0=未评
    resolution_ok: Mapped[int] = mapped_column(Integer, default=0)  # 问题是否真正解决（0/1）
    source: Mapped[str] = mapped_column(String(16), default="judge")  # judge/rule/manual
    reviewer: Mapped[str] = mapped_column(String(64), default="")  # 人工改评者；自动评为空
    detail: Mapped[str] = mapped_column(Text, default="{}")  # 各维分/依据/judge 原文（截断）
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
