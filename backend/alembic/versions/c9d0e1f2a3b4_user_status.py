"""用户状态列（FR-12.4 离职一键冻结：users.status，对齐数据模型 §2）

链路：alembic upgrade head → users 加 status 列（默认 active）→ auth_service.authenticate
      拒登 frozen 账号；行保留以便会话/绩效/审计仍能回溯到人。
向前兼容：只加字段（server_default='active'），存量行自动为 active，旧代码读不到该列也不报错；
          回滚删列（回滚前请确认没有依赖冻结态的业务，冻结是权限手段非数据手段）。
挂点：b8c9d0e1f2a3（管理后台扩展表）之后，保持单头。

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
    )
    op.create_index("ix_users_status", "users", ["status"])


def downgrade() -> None:
    op.drop_index("ix_users_status", table_name="users")
    op.drop_column("users", "status")
