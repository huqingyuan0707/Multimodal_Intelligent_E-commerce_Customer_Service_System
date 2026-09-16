"""转人工技能组路由字段（C 步余项：sessions 加 handoff_skill 列，对齐数据模型 §2）

链路：alembic upgrade head → sessions 加 handoff_skill（存量行 server_default 回填
general）→ handoff_service 挂起时按规则表写组 → 队列筛选/认领门禁/智能分配读它。
向前兼容：只加列不改列，旧代码读写不受影响；回滚删列。
挂点：squash 基线 12cb8192e4f1（旧 4 条迁移已压平，勿再挂 e4f5a6b7c8d9）。

Revision ID: b7c2d4e6f8a1
Revises: 12cb8192e4f1
Create Date: 2026-09-16
"""

import sqlalchemy as sa

from alembic import op

revision = "b7c2d4e6f8a1"
down_revision = "12cb8192e4f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column("handoff_skill", sa.String(32), server_default="general", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("handoff_skill")
