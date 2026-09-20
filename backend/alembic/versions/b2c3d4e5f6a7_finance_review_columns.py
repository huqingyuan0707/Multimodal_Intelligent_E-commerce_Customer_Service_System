"""财务双人复核两列（finance_bills 加 reviewed_by/reviewed_at，对齐 FR-10.5 制单复核分离）

链路：alembic upgrade head → finance_bills 补复核两列 → finance_service.settle（制单）/
      confirm_settle（复核结清）两步落地 → /finance 页「制单 → 复核」按钮两段式。
向前兼容：纯新增可空/带默认列，不动存量数据；历史已日结行 reviewed_by 由种子回填。
挂点：a1b2c3d4e5f6（B 端四表）之后，保持单头。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "finance_bills",
        sa.Column("reviewed_by", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column("finance_bills", sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("finance_bills", "reviewed_at")
    op.drop_column("finance_bills", "reviewed_by")
