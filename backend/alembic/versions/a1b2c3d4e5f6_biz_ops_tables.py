"""B 端二期与风控四表（采购/财务/风控，FR-10.3/FR-10.5/FR-12.1）

链路：alembic upgrade head → 建 suppliers / purchase_orders / finance_bills / risk_events
      → procurement/finance/risk 服务按 tenant 读写 → /purchase、/finance、/risk 接真数据。
向前兼容：纯新增表 + 索引，不动存量表；downgrade 逆序删表（先删带外键的 purchase_orders）。
挂点：d7e8f9a0b1c2（售后质检处置列）之后，保持单头。

Revision ID: a1b2c3d4e5f6
Revises: d7e8f9a0b1c2
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("pay_terms", sa.String(64), nullable=False, server_default=""),
        sa.Column("pass_rate", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_suppliers_tenant", "suppliers", ["tenant"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.String(32), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("warehouse_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("items", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("eta", sa.String(16), nullable=False, server_default=""),
        sa.Column("qc_result", sa.String(16), nullable=False, server_default=""),
        sa.Column("qc_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_orders_tenant", "purchase_orders", ["tenant"])
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_warehouse_id", "purchase_orders", ["warehouse_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])

    op.create_table(
        "finance_bills",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("biz_date", sa.String(16), nullable=False),
        sa.Column("receivable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refund", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fee", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("freight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("diff", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settled_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant", "biz_date", name="uq_finance_bill_date"),
    )
    op.create_index("ix_finance_bills_tenant", "finance_bills", ["tenant"])
    op.create_index("ix_finance_bills_biz_date", "finance_bills", ["biz_date"])

    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("user_ref", sa.String(64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default="order_risk"),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewer", sa.String(64), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_risk_events_tenant", "risk_events", ["tenant"])
    op.create_index("ix_risk_events_user_ref", "risk_events", ["user_ref"])
    op.create_index("ix_risk_events_kind", "risk_events", ["kind"])
    op.create_index("ix_risk_events_status", "risk_events", ["status"])


def downgrade() -> None:
    op.drop_table("risk_events")
    op.drop_table("finance_bills")
    op.drop_table("purchase_orders")
    op.drop_table("suppliers")
