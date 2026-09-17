"""成本归因来源列（cost_records.pricing_source，对齐数据模型 §2 成本归因）

链路：alembic upgrade head → cost_records 加 pricing_source（usage/estimate）
      → chat_turn_store 双写 → 看板估算占比口径。
向前兼容：只加列（server_default estimate），旧行即估算口径，回滚删列。
挂点：f2a3b4c5d6e7（知识库生命周期版本）之后；记忆迁移 e5f6a7b8c9d0
挂在本迁移之后，全链 f2a3→d9e8→e5f6 单头（e5f6 先发现本文件已挂好，
切勿再把本迁移后挂 e5f6，否则成环）。

Revision ID: d9e8f7a6b5c4
Revises: f2a3b4c5d6e7
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "d9e8f7a6b5c4"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cost_records",
        sa.Column("pricing_source", sa.String(16), server_default="estimate", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cost_records", "pricing_source")
