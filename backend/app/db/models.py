"""ORM 模型（最小 P0 集，对齐数据模型文档 §2）

链路：session.create_tables 建表 → services 读写 → scripts/init_db.py 灌种子用户。
SQLite 无原生 UUID/数组类型，一律用 String/JSON 文本，PG 迁移时再收紧。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
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
