"""知识库生命周期与版本历史（FR-13.2/FR-13.5，对齐数据模型 §KB）

链路：alembic upgrade head → kb_docs 加 topic/status/submitted_by/published_by
      （存量默认 published，行为不变）+ 新建 kb_doc_versions 只追加表
      → document_service 生命周期/回滚/引用统计读写。
向前兼容：只加列加表；status 默认 published 保证存量检索不受影响；回滚删表删列。
挂点：d4e5f6a7b8c9（Prompt Studio 表）之后，保持单头不断链。

Revision ID: f2a3b4c5d6e7
Revises: d4e5f6a7b8c9
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_docs", sa.Column("topic", sa.String(64), server_default=""))
    op.add_column(
        "kb_docs", sa.Column("status", sa.String(16), server_default="published", index=True)
    )
    op.add_column("kb_docs", sa.Column("submitted_by", sa.String(64), server_default=""))
    op.add_column("kb_docs", sa.Column("published_by", sa.String(64), server_default=""))
    op.create_table(
        "kb_doc_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("doc_id", sa.String(32), nullable=False, index=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(200), server_default=""),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("sha256", sa.String(64), server_default=""),
        sa.Column("actor", sa.String(64), server_default=""),
        sa.Column("action", sa.String(16), server_default="create", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["doc_id"], ["kb_docs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("kb_doc_versions")
    op.drop_column("kb_docs", "published_by")
    op.drop_column("kb_docs", "submitted_by")
    op.drop_column("kb_docs", "status")
    op.drop_column("kb_docs", "topic")
