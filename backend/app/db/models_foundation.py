"""前置地基模型（会话消息/任务/工具调用/知识库/成本，对齐数据模型文档 §2）

链路：alembic 基线迁移建表 → session/task/document 服务按 tenant 读写 → 各页面接真数据。
口径：主键 String(32) uuid hex；业务表必带 tenant 字符串（与 users.tenant 同源）；
金额整数分；JSON 列用 Text 存 JSON 文本（SQLite 无数组/JSONB，PG 迁移再收紧）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid


class Message(Base):
    """会话消息（多模态+引用+trace，级联随会话删除）。

    client_msg_id：前端每次发送生成的幂等键（user/agent 同值配对），重连复用同一键
    不再插新行，保证“断网重连不重复消息”。
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[str] = mapped_column(Text, default="[]")
    citations: Mapped[str] = mapped_column(Text, default="[]")
    guard: Mapped[str] = mapped_column(Text, default="{}")
    faithfulness: Mapped[float | None] = mapped_column(Float, default=None)
    trace_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    client_msg_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Task(Base):
    """异步任务（长任务提交/轮询/检查点，状态机 pending/running/done/failed）。"""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(48), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    input: Mapped[str] = mapped_column(Text, default="{}")
    output: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="{}")
    checkpoint: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ToolCall(Base):
    """工具调用审计（谁/何时/调什么/结果/耗时，全量留痕）。

    on_behalf_of：跨系统「代表谁」——外部 Agent（office-agent）以服务账号身份调用时，
    username 记调用方（服务账号），本列记真实发起人，保证审批/审计的追责链不断在人机边界。
    """

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    trace_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    tenant: Mapped[str] = mapped_column(String(64), default="", index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    on_behalf_of: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(64), default="", index=True)
    args: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class KbDoc(Base):
    """知识库文档（主题/版本/生效期/密级/生命周期，sha256 租户内去重）。

    链路：上传/种子默认 published（存量兼容）；运营新建走 draft→review→published→archived
    （FR-13.2）；检索 SQL 只收 published；topic 供引用统计按主题聚合。
    """

    __tablename__ = "kb_docs"
    __table_args__ = (UniqueConstraint("tenant", "sha256", name="uq_kb_docs_tenant_sha"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    submitted_by: Mapped[str] = mapped_column(String(64), default="")
    published_by: Mapped[str] = mapped_column(String(64), default="")
    channels: Mapped[str] = mapped_column(Text, default='["all"]')
    security_level: Mapped[str] = mapped_column(String(16), default="internal")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class KbChunk(Base):
    """知识分块（向量 ID 桥接向量库，删除文档级联）。"""

    __tablename__ = "kb_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("kb_docs.id", ondelete="CASCADE"), index=True)
    ord: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    vector_id: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


# 生命周期状态机（FR-13.2）：draft→review→published→archived（archived 可 reopen 回 draft）
KB_DOC_STATUS = ("draft", "review", "published", "archived")


class KbDocVersion(Base):
    """文档版本历史（只追加：新建/编辑/发布/回滚各落一行，回滚=旧内容新版本）。

    链路：document_service._snapshot_version → GET /documents/{id}/versions 列表 →
         POST /documents/{id}/rollback 恢复。
    """

    __tablename__ = "kb_doc_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("kb_docs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    actor: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(16), default="create")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class CostRecord(Base):
    """成本归因（按租户/会话/模型记 token 与费用分）。"""

    __tablename__ = "cost_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    # 定价来源：usage=上游 tokens 实数，estimate=estimate_tokens 估算；
    # 归因误差度量 = estimate 费用占比（越低越准），看板成本卡同口径
    pricing_source: Mapped[str] = mapped_column(String(16), default="estimate")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Feedback(Base):
    """问答反馈（Mining 闭环输入：差评/纠错聚成待补知识，租户隔离）。

    链路：chat 落库 message → POST /mining/feedback → 本表 → candidates 聚类 → reindex。
    """

    __tablename__ = "feedbacks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    vote: Mapped[str] = mapped_column(String(16), default="down")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class UserPreference(Base):
    """长期偏好（FR-4：用户级键值记忆，需显式"记住"授权才写，PII 永不进）。

    链路：memory_service.record_turn（显式信号）→ upsert → recall_prefs 拼【长期偏好】进 LLM；
         forget_user 按户清（GDPR 一键遗忘）。
    口径：(tenant, username, key) 唯一；value 短文本（≤64 字）；source=explicit（写死，防未来杂源）。
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("tenant", "username", "key", name="uq_prefs_tenant_user_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="explicit")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
