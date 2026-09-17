"""长期偏好表（FR-4 收官：user_preferences，对齐数据模型 §2 + FRD FR-4「长期偏好」）

链路：alembic upgrade head → 新建 user_preferences 表（租户+用户+键唯一，同键原地覆盖）
      → memory_service 读写 → 历史块【长期偏好】/ 一键遗忘按户清。
向前兼容：只加表不改列，旧代码不受影响；回滚删表。
挂点：d9e8f7a6b5c4（成本定价来源列）之后（与之同起于 f2a3b4c5d6e7，本文件后挂保持单头）。

Revision ID: e5f6a7b8c9d0
Revises: d9e8f7a6b5c4
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d9e8f7a6b5c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("username", sa.String(64), nullable=False, index=True),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), server_default="explicit", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant", "username", "key", name="uq_prefs_tenant_user_key"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
