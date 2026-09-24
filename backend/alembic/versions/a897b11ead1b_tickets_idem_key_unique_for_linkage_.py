"""tickets idem_key unique for linkage writeback

Revision ID: a897b11ead1b
Revises: e1f2a3b4c5d6
Create Date: 2026-09-24 14:07:18.893880

"""
from alembic import op
import sqlalchemy as sa


revision = 'a897b11ead1b'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 不支持 ALTER 约束，用 batch 模式（copy-and-move）一次完成加列 + 唯一约束。
    # finance_bills 的 uq_finance_bill_date 漂移与本次无关（存量债务），不混入本迁移。
    with op.batch_alter_table(
        "tickets",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        batch_op.add_column(sa.Column("idem_key", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_tickets_tenant_idem", ["tenant", "idem_key"])


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("uq_tickets_tenant_idem", type_="unique")
        batch_op.drop_column("idem_key")
