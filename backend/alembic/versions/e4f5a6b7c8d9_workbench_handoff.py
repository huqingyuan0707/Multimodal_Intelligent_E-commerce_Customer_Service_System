"""坐席流转字段（C 步转人工：sessions 挂起态 + 认领人 + 内部备注表，对齐数据模型 §2）

链路：alembic upgrade head → sessions 加 4 列（存量行 server_default 回填）+
新建 session_notes 表 → workbench_service 读写流转 → WorkbenchView 接真队列。
向前兼容：只加列加表不改列，旧代码读写不受影响；回滚删表删列。

Revision ID: e4f5a6b7c8d9
Revises: d3f1a2b4c5e6
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3f1a2b4c5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column("handoff_status", sa.String(16), server_default="none", nullable=False)
        )
        batch.add_column(sa.Column("assignee", sa.String(64), server_default="", nullable=False))
        batch.add_column(
            sa.Column("handoff_reason", sa.String(200), server_default="", nullable=False)
        )
        batch.add_column(sa.Column("resolution", sa.Text(), server_default="", nullable=False))
    op.create_table(
        "session_notes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(32), nullable=False, index=True),
        sa.Column("author", sa.String(64), server_default=""),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    # 队列按挂起态过滤，与 models.Session.handoff_status(index=True) 对齐，避免 alembic 建库与 create_all 建库漂移
    op.create_index("ix_sessions_handoff_status", "sessions", ["handoff_status"])


def downgrade() -> None:
    op.drop_table("session_notes")
    op.drop_index("ix_sessions_handoff_status", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("resolution")
        batch.drop_column("handoff_reason")
        batch.drop_column("assignee")
        batch.drop_column("handoff_status")
