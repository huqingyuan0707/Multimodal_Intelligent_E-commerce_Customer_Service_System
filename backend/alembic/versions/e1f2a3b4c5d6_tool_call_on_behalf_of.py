"""工具调用审计补 on_behalf_of（跨系统身份透传留痕，对齐联动方案 §7.3）

链路：外部 Agent（office-agent）以服务账号令牌 + X-On-Behalf-Of 调 /agent-gateway/invoke
      → 服务账号白名单采纳该头 → executor._audit 落 tool_calls.on_behalf_of。
口径：username 记调用方（服务账号），on_behalf_of 记真实发起人——追责链不断在人机边界。
向前兼容：纯新增带默认值列，存量行自动为空串，旧代码读不到该列也不报错；回滚删列。
挂点：b2c3d4e5f6a7（财务双人复核列）之后，保持单头。

Revision ID: e1f2a3b4c5d6
Revises: b2c3d4e5f6a7
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("on_behalf_of", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("tool_calls", "on_behalf_of")