"""Agent Studio 两表（Prompt 版本 + 评测 runs，对齐数据模型 §2 + FRD FR-3「Prompt 版本灰度」）

链路：alembic upgrade head → 新建 prompt_versions / eval_runs 表
      → studio_service 读写 → /studio 端点 → StudioView 三窗格。
附带补齐 messages.cost_cents 列（Message 模型已有字段，补迁移使 autogenerate 对齐）。
向前兼容：只加表加列不改列，旧代码不受影响；回滚删表删列。
挂点：c8d3e5f7a9b2（质检评分表）之后。

Revision ID: d4e5f6a7b8c9
Revises: c8d3e5f7a9b2
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c8d3e5f7a9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("desc", sa.String(200), server_default="", nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("variables", sa.Text(), server_default="[]", nullable=False),
        sa.Column("gray", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False, index=True),
        sa.Column("created_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant", "version", name="uq_prompts_tenant_version"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(64), server_default="default-200", nullable=False),
        sa.Column("limit", sa.Integer(), server_default="50", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False, index=True),
        sa.Column("score", sa.Text(), server_default="{}", nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(500), server_default="", nullable=False),
        sa.Column("created_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    # messages.cost_cents：模型字段先行（成本折算落库），本迁移补齐列（旧库默认 0）。
    op.add_column("messages", sa.Column("cost_cents", sa.Integer(), server_default="0"))


def downgrade() -> None:
    op.drop_column("messages", "cost_cents")
    op.drop_table("eval_runs")
    op.drop_table("prompt_versions")
