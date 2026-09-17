"""ORM 模型（最小 P0 集，对齐数据模型文档 §2）

链路：session.create_tables 建表 → services 读写 → scripts/init_db.py 灌种子用户。
SQLite 无原生 UUID/数组类型，一律用 String/JSON 文本，PG 迁移时再收紧。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid

# 前置地基表（messages/tasks/tool_calls/kb_docs/kb_chunks/cost_records）见 models_foundation，
# 质检评分表见 models_quality，Studio（Prompt 版本/评测 runs）见 models_studio；
# 此处重导出以保持 `from app.db.models import X` 口径唯一，Alembic env 同步 import 各模块。
from app.db.models_foundation import (
    CostRecord,
    Feedback,
    KbChunk,
    KbDoc,
    KbDocVersion,
    Message,
    Task,
    ToolCall,
    UserPreference,
)
from app.db.models_quality import SessionScore
from app.db.models_studio import EvalRun, PromptVersion

__all__ = [
    "Base",
    "CostRecord",
    "EvalRun",
    "Feedback",
    "KbChunk",
    "KbDoc",
    "KbDocVersion",
    "Message",
    "PromptVersion",
    "Session",
    "SessionNote",
    "SessionScore",
    "Task",
    "ToolCall",
    "User",
    "UserPreference",
]


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
    """会话（三层之首：归属 + 标题 + 长会话摘要 + 活跃时间，消息见 messages 表）。

    summary：超 SESSION_HISTORY_ROUNDS 轮时由 context_service 规则摘要写入，
    下轮拼进 LLM 上下文，老消息不再逐条注入（双重修剪之轮数侧）。
    handoff_status：坐席流转 none→pending（待接）→handling（处理中）→resolved（已解决），
    由 workbench_service 读写（买家转人工/拒答/低置信自动挂起，坐席认领/解决）。
    handoff_skill：挂起时按规则表路由到的技能组（口径见 handoff_rules.HANDOFF_SKILL_GROUPS：
    general 通用 + refund/complaint/aftersale 专组）；队列筛选、认领门禁、智能分配都读它。
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    summary: Mapped[str] = mapped_column(Text, default="")
    handoff_status: Mapped[str] = mapped_column(String(16), default="none", index=True)
    assignee: Mapped[str] = mapped_column(String(64), default="")
    handoff_reason: Mapped[str] = mapped_column(String(200), default="")
    handoff_skill: Mapped[str] = mapped_column(String(32), default="general")
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class SessionNote(Base):
    """坐席内部备注（买家不可见：只经 workbench 端点读写，无买家侧查询口）。

    链路：WorkbenchView 备注抽屉 → workbench_service.add_note → 本表（租户隔离）。
    """

    __tablename__ = "session_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


# ==================== B 端业务域（商品/库存/订单/审批，数据模型文档 §2.1） ====================
# 统一口径（写代码前先对齐这里，禁止各页自定）：
# - 主键沿用 String(32) uuid hex（与 users/sessions 同构，PG 迁移直接换 uuid 类型）。
# - 每张业务表都带 tenant 列，服务层所有查询强制按租户过滤（越权红线）。
# - 金额一律整数「分」（禁浮点），展示层由前端统一分转元。
# - 状态是受控字符串，服务层枚举校验，非法流转返回 3005。


class Product(Base):
    """SPU：/goods 主行；images/attrs 存 JSON 文本（材质/洗涤方式等扩展属性）。"""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant", "spu_no", name="uq_product_spu"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    spu_no: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="")
    images: Mapped[str] = mapped_column(Text, default="[]")
    attrs: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/on/off
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Sku(Base):
    """SKU：颜色 × 尺码行级；list_price=吊牌价、sale_price=售价（分）。"""

    __tablename__ = "skus"
    __table_args__ = (UniqueConstraint("product_id", "color", "size", name="uq_sku_variant"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    color: Mapped[str] = mapped_column(String(40), default="")
    size: Mapped[str] = mapped_column(String(20), default="")
    barcode: Mapped[str] = mapped_column(String(64), default="")
    list_price: Mapped[int] = mapped_column(Integer, default=0)
    sale_price: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="on")  # on/off


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("tenant", "name", name="uq_warehouse_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Inventory(Base):
    """库存行：available = qty - reserved - locked（唯一口径，见 inventory_service）。"""

    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("warehouse_id", "sku_id", name="uq_inventory_row"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[int] = mapped_column(Integer, default=0)
    warn_line: Mapped[int] = mapped_column(Integer, default=10)


class StockMove(Base):
    """出入库流水：每行必须带原因（缺原因 1001）；调拨拆「出 A 仓 + 入 B 仓」两行。"""

    __tablename__ = "stock_moves"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # in/out/move/adjust
    delta: Mapped[int] = mapped_column(Integer, default=0)
    order_ref: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(String(200), default="")
    actor: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class SalesOrder(Base):
    """订单本地镜像：幂等键 (tenant, platform, outer_id)；items 为行快照 JSON。"""

    __tablename__ = "sales_orders"
    __table_args__ = (UniqueConstraint("tenant", "platform", "outer_id", name="uq_order_outer"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20))
    outer_id: Mapped[str] = mapped_column(String(64))
    items: Mapped[str] = mapped_column(Text, default="[]")
    total: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending_pay", index=True)
    trace_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class LogisticsOrder(Base):
    """面单：发货成功后落行，tracking_no 已在服务层做格式校验。"""

    __tablename__ = "logistics_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sales_order_id: Mapped[str] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    company: Mapped[str] = mapped_column(String(40), default="")
    tracking_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created/picked/in_transit
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Aftersale(Base):
    """售后单：trace_id 关联会话，供 /orders 抽屉一键跳 workbench 回放。"""

    __tablename__ = "aftersales"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sales_order_id: Mapped[str] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[str] = mapped_column(Text, default="[]")
    trace_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approving/done
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Approval(Base):
    """审批流：改价 / 盘点差异 / 超阈值退款恒进审批（args 存生效所需参数 JSON）。"""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(40), default="")
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str] = mapped_column(String(120), default="")
    args: Mapped[str] = mapped_column(Text, default="{}")
    reason: Mapped[str] = mapped_column(String(200), default="")
    applicant: Mapped[str] = mapped_column(String(64), default="")
    approver: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)


class Promo(Base):
    """营销活动（预算原子扣减，超发 3006；对齐 FRD FR-10.6/附录 F）"""

    __tablename__ = "promos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    budget: Mapped[int] = mapped_column(Integer, default=0)
    granted: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    per_user: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime | None] = mapped_column(default=None)
    valid_to: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class CouponGrant(Base):
    """发券记录（idem_key 唯一防重放，对齐 FRD 附录 F）"""

    __tablename__ = "coupon_grants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    promo_id: Mapped[str] = mapped_column(ForeignKey("promos.id"), index=True)
    user_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    order_ref: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="granted")
    idem_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    __table_args__ = (UniqueConstraint("tenant", "idem_key", name="uq_grants_tenant_idem"),)


class Member(Base):
    """会员（等级/积分，服装复购；对齐 FRD FR-10.6）"""

    __tablename__ = "members"

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)
    user_ref: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="v0")
    points: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Review(Base):
    """评价（差评 ticket_id 双向可跳；对齐 FRD FR-10.8/附录 F）"""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    outer_id: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="good", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    replied: Mapped[bool] = mapped_column(default=False)
    reply: Mapped[str] = mapped_column(Text, default="")
    ticket_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Ticket(Base):
    """协同工单（SLA+关闭回填结论；对齐 FRD FR-12.3/附录 F）"""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="general", index=True)
    source_ref: Mapped[str] = mapped_column(String(64), default="")
    assignee: Mapped[str] = mapped_column(String(64), default="")
    sla_due: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    conclusion: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


# ==================== 管理后台（租户/配额/审计，对齐 FRD FR-8/数据模型 §2） ====================
# 口径：
# - Tenant.code 即全站 tenant 字符串（users.tenant / 业务表 tenant 同源），唯一。
# - 配额只做框架：quota_tokens（Token 总量）/ quota_concurrency（并发上限），超限限流后续接网关。
# - 审计只追加不改：任何租户/配额/角色变更必须同步记一条 audit_logs。


class Tenant(Base):
    """租户（订阅/配额/停服；code 与 users.tenant 同源字符串）。"""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("code", name="uq_tenants_code"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    plan: Mapped[str] = mapped_column(String(16), default="trial")  # trial/basic/pro/enterprise
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/suspended/disabled
    quota_tokens: Mapped[int] = mapped_column(Integer, default=1000000)
    quota_concurrency: Mapped[int] = mapped_column(Integer, default=50)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class AuditLog(Base):
    """审计（谁/何时/干什么/结果；只追加不改，留痕≥6 个月）。"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), default="", index=True)
    actor: Mapped[str] = mapped_column(String(64), default="", index=True)
    action: Mapped[str] = mapped_column(String(64), default="", index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
