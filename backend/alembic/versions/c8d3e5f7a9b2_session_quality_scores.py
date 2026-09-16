"""会话质检评分表（C 步收官：session_scores，对齐数据模型 §2 + FRD FR-7「质检打分」）

链路：alembic upgrade head → 新建 session_scores 表（租户+会话唯一，重评原地覆盖）
      → quality_service 读写 → 坐席绩效面板 / 会话详情读取。
向前兼容：只加表不改列，旧代码不受影响；回滚删表。
挂点：b7c2d4e6f8a1（技能组路由列）之后。

Revision ID: c8d3e5f7a9b2
Revises: b7c2d4e6f8a1
Create Date: 2026-09-16
"""

import sqlalchemy as sa

from alembic import op

revision = "c8d3e5f7a9b2"
down_revision = "b7c2d4e6f8a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_scores",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(32), nullable=False, index=True),
        sa.Column("assignee", sa.String(64), server_default="", index=True),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("resolution_ok", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(16), server_default="judge", nullable=False),
        sa.Column("reviewer", sa.String(64), server_default="", nullable=False),
        sa.Column("detail", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant", "session_id", name="uq_scores_tenant_session"),
    )


def downgrade() -> None:
    op.drop_table("session_scores")
