"""会话上下文层字段（历史对话三层：summary 长会话摘要 + updated_at 活跃排序，对齐数据模型 §2）

链路：alembic upgrade head → sessions 加两列（存量行 server_default 回填）→
context_service 读写摘要 → run_text_turn 拼历史进 LLM。
向前兼容：只加列不改列，旧代码读写不受影响；回滚直接删列。

Revision ID: d3f1a2b4c5e6
Revises: 6aea96793dc7
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "d3f1a2b4c5e6"
down_revision = "6aea96793dc7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("summary", sa.Text(), server_default="", nullable=False))
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("summary")
