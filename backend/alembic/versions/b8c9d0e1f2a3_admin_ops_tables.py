"""管理后台扩展表（api_keys/slo_rules/message_templates/shifts，对齐数据模型 §2 + FRD FR-8/FR-12.2/12.4）

链路：alembic upgrade head → 建 4 张表 → admin 各服务读写 → /admin 密钥/SLO/消息/组织窗格接真数据。
向前兼容：只加表不改列，旧代码不受影响；回滚删 4 张表。
挂点：e5f6a7b8c9d0（user_preferences）之后，保持单头。

Revision ID: b8c9d0e1f2a3
Revises: e5f6a7b8c9d0
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(24), server_default="", nullable=False),
        sa.Column("masked", sa.String(48), server_default="", nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.String(300), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False, index=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant", "name", name="uq_apikeys_tenant_name"),
        sa.UniqueConstraint("key_hash", name="uq_apikeys_hash"),
    )
    op.create_table(
        "slo_rules",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(4), server_default="gte", nullable=False),
        sa.Column("threshold", sa.Float(), server_default="0", nullable=False),
        sa.Column("window", sa.String(16), server_default="realtime", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.String(200), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant", "metric", name="uq_slo_tenant_metric"),
    )
    op.create_table(
        "message_templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), server_default="sms", nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False, index=True),
        sa.Column("reach_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reach_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant", "name", name="uq_tpl_tenant_name"),
    )
    op.create_table(
        "shifts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, index=True),
        sa.Column("username", sa.String(64), nullable=False, index=True),
        sa.Column("work_date", sa.String(10), nullable=False, index=True),
        sa.Column("start_time", sa.String(5), server_default="09:00", nullable=False),
        sa.Column("end_time", sa.String(5), server_default="18:00", nullable=False),
        sa.Column("skill", sa.String(32), server_default="general", nullable=False),
        sa.Column("note", sa.String(200), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shifts")
    op.drop_table("message_templates")
    op.drop_table("slo_rules")
    op.drop_table("api_keys")
