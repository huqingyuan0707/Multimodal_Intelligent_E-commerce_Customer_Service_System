"""售后单质检处置列（FR-10.4 退货质检 → 二次入库/报损/退供）

链路：alembic upgrade head → aftersales 加 disposition 列（默认 pending）
      → order_service.dispose() 按处置类型执行库存 move + 状态流转。
向前兼容：只加列，server_default='pending'，存量行 disposition=pending 不触发处置动作，旧代码不报错。
挂点：c9d0e1f2a3b4（用户状态列）之后，保持单头。

Revision ID: d7e8f9a0b1c2
Revises: c9d0e1f2a3b4
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aftersales",
        sa.Column("disposition", sa.String(16), server_default="pending", nullable=False),
    )
    op.create_index("ix_aftersales_disposition", "aftersales", ["disposition"])


def downgrade() -> None:
    op.drop_index("ix_aftersales_disposition", table_name="aftersales")
    op.drop_column("aftersales", "disposition")
