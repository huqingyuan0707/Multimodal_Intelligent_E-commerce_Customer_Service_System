"""管理后台扩展模型（密钥/SLO 规则/消息模板/排班，对齐数据模型 §2 + FRD FR-8/FR-12.2/FR-12.4）

链路：alembic 迁移建表 → admin 相关服务按 tenant 读写 → `/admin` 各窗格接真数据。
口径（写代码前先对齐这里，禁止各窗格自定）：
- 密钥只存 sha256 摘要，明文仅在创建/轮换的响应里返回一次，此后任何接口都只回掩码；
- SLO 规则只存「阈值口径」，实时值一律从 observability.snapshot() 现取（规则表不存历史值，
  避免两处事实源）；触发与否由服务层当场比对，不落冗余状态；
- 消息模板只存模板本身，发送频控走 core/cache 计数（与对话限流同一适配层）；
- 排班 work_date 存 "YYYY-MM-DD" 文本（字典序即时间序，SQLite/PG 行为一致）；
- 全部写操作同步记 `audit_logs`（只追加不改）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid

# 密钥状态机（active 可用 / disabled 已禁用，禁用后校验直接拒，不删行以便留痕）
API_KEY_STATUSES = ("active", "disabled")
# SLO 比较方向：gte=目标为下限（值 ≥ 阈值才达标，如接起率）、lte=目标为上限（值 ≤ 阈值才达标，如 P95）
SLO_OPERATORS = ("gte", "lte")
# 聚合窗口：现阶段只有 realtime（core/observability 内存聚合）。
# today/week 需要 JSONL 历史报表（E 步评估流水线），尚未实现 —— 故不列进白名单，
# 避免「下拉里能选、实际算不出来」这种假能力。
SLO_WINDOWS = ("realtime",)
TEMPLATE_CHANNELS = ("sms", "wechat", "dingtalk", "email")
TEMPLATE_STATUSES = ("draft", "active", "disabled")


class ApiKey(Base):
    """API 密钥（**只存 sha256 摘要**，明文仅创建/轮换响应返回一次）。

    链路：AdminView 密钥窗格 → endpoints/admin → api_key_service → 本表；
        列表只回 `prefix/masked`，轮换即换新口令并把旧摘要覆盖（旧口令立刻失效）。
    红线：任何读取路径都不得回明文或摘要——明文只在 create/rotate 的返回值里出现一次。
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("tenant", "name", name="uq_apikeys_tenant_name"),
        UniqueConstraint("key_hash", name="uq_apikeys_hash"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    prefix: Mapped[str] = mapped_column(String(24), default="")
    masked: Mapped[str] = mapped_column(String(48), default="")
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class SloRule(Base):
    """SLO 阈值规则（指标 + 方向 + 阈值 + 窗口 + 开关）。

    链路：/admin SLO 窗格 → slo_service → 本表（口径）+ observability.snapshot()（实时值）
         → 当场比对得出 breach/ok 与当前值，规则表不落「当前是否超标」的冗余状态。
    """

    __tablename__ = "slo_rules"
    __table_args__ = (UniqueConstraint("tenant", "metric", name="uq_slo_tenant_metric"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(4), default="gte")
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    window: Mapped[str] = mapped_column(String(16), default="realtime")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class MessageTemplate(Base):
    """消息模板（渠道 + 名称 + 正文，正文可用 {user_ref} 占位）。

    链路：/admin 消息窗格维护 → 发送侧按 name 取模板渲染 → 频控走 core/cache 计数。
    口径：name 租户内唯一；只有 status=active 的模板可被发送侧使用。
    """

    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("tenant", "name", name="uq_tpl_tenant_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="sms")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    reach_total: Mapped[int] = mapped_column(Integer, default=0)
    reach_failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Shift(Base):
    """客服排班（人 + 日期 + 时段 + 技能组），一天可多段。

    链路：/admin 组织窗格维护 → 与 handoff_rules 的技能组口径对齐（general/refund/complaint/aftersale）
         → 供「此刻谁在线」与绩效到人两个视图共读。
    work_date 用 "YYYY-MM-DD" 文本：字典序等于时间序，SQLite/PG 行为一致，免时区歧义。
    """

    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    work_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    start_time: Mapped[str] = mapped_column(String(5), default="09:00")
    end_time: Mapped[str] = mapped_column(String(5), default="18:00")
    skill: Mapped[str] = mapped_column(String(32), default="general")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
