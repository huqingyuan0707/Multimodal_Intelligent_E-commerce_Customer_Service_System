"""B 端二期与风控表（采购/财务/风控，对齐数据模型与存储设计.md §2.1/§2.2 DDL）

链路：alembic 迁移建表 → procurement/finance/risk 服务按 tenant 读写
      → /purchase、/finance、/risk 三页接真数据（TicketCenter 复用既有 tickets 表）。
口径（写代码前先对齐这里，禁止各服务自定）：
- 金额一律整数分；日期存 "YYYY-MM-DD" 文本（字典序即时间序，SQLite/PG 行为一致，同 shifts.work_date）；
- 采购单状态机唯一合法路径 draft→approved→received→stocked，rejected/returned 为两条失败终态；
  质检合格才写 inventory + stock_moves（审批前不动账，与改价/盘点「批准才生效」同一红线）；
- 风控只做「人工复核留痕」，禁全自动封号：block 必留 reviewer，不写 users.status；
- 采购/财务/风控写操作同步记 audit_logs（只追加不改）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, _now, _uid

# 采购单状态机（唯一合法路径 draft→approved→received→stocked）
PURCHASE_STATUSES = ("draft", "approved", "rejected", "received", "stocked", "returned")
# 质检结论：pass=合格入库 / fail=不合格退供
QC_RESULTS = ("pass", "fail")
# 风控事件状态：pending 待复核 / passed 放行 / blocked 拦截（拦截必进人工复核，不自动封号）
RISK_STATUSES = ("pending", "passed", "blocked")


class Supplier(Base):
    """供应商（账期 + 历史合格率，供采购单选择与到货质检回溯）。"""

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pay_terms: Mapped[str] = mapped_column(String(64), default="")  # 账期（如「月结 30 天」）
    pass_rate: Mapped[float] = mapped_column(Float, default=1.0)  # 历史合格率 0~1
    created_at: Mapped[datetime] = mapped_column(default=_now)


class PurchaseOrder(Base):
    """采购单（草稿→审批→到货→质检→入库；items 为行快照 JSON）。

    items 行口径：`[{"sku_id","name","color","size","qty","price"}]`，price 为分/件。
    收货仓 warehouse_id 在质检合格时用于入库；未指定为空串，质检时会拒（1001）。
    """

    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_id: Mapped[str | None] = mapped_column(
        ForeignKey("suppliers.id"), default=None, index=True
    )
    warehouse_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    items: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    eta: Mapped[str] = mapped_column(String(16), default="")  # 预计到货日 "YYYY-MM-DD"
    qc_result: Mapped[str] = mapped_column(String(16), default="")  # pass/fail，仅质检后非空
    qc_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class FinanceBill(Base):
    """日结单（应收/实收/退款/运费/扣点/差异，金额分；无 PII 列）。

    diff = received - (receivable - refund - fee + freight)（口径唯一出处见 finance_service）。
    双人复核两步（v0.3.32 起启用）：settled_by=制单人（第一步日结制单），reviewed_by=复核人
    （第二步复核结清，不得与制单人同一账号）；出参 settled = reviewed_by 非空。
    """

    __tablename__ = "finance_bills"
    # 一个租户一个账期只有一张日结单（settle 按 (tenant, biz_date) 取单，靠此约束兜底防重）
    __table_args__ = (UniqueConstraint("tenant", "biz_date", name="uq_finance_bill_date"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    biz_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    receivable: Mapped[int] = mapped_column(Integer, default=0)
    received: Mapped[int] = mapped_column(Integer, default=0)
    refund: Mapped[int] = mapped_column(Integer, default=0)
    fee: Mapped[int] = mapped_column(Integer, default=0)
    freight: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[int] = mapped_column(Integer, default=0)
    settled_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class RiskEvent(Base):
    """风控事件（关联图谱摘要存 detail；通过/拦截必留 reviewer，禁全自动封号）。"""

    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_ref: Mapped[str] = mapped_column(String(64), default="", index=True)
    kind: Mapped[str] = mapped_column(String(32), default="order_risk", index=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
