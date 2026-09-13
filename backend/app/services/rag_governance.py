"""RAG 治理服务（每步的租户隔离 + 生效期过滤 + 审计留痕，对齐 RAG 规范 §3）

链路：各 service 在关键步骤调 trace_step（observability 留痕，不碰 DB 事务）
      → 写操作再调 audit_write（audit_logs 只追加）。
红线：绝不信任请求体 tenant；生效期空端=不限；过滤原因随 retrieval 调试返回。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import record

# ---------------- 生效期 ----------------


def is_valid_now(valid_from: Any, valid_to: Any, now: datetime | None = None) -> bool:
    """生效期判定：空端不限；naive 时间按裸值比较（与落库口径一致，纯函数可单测）。"""
    moment = now or datetime.now()
    if isinstance(valid_from, datetime) and moment < valid_from.replace(tzinfo=None):
        return False
    return not (isinstance(valid_to, datetime) and moment > valid_to.replace(tzinfo=None))


def channel_visible(doc_channels: list[str], wanted: str = "all") -> bool:
    """渠道过滤：doc 含 all 或命中请求渠道即放行（纯函数可单测）。"""
    if not wanted or wanted == "all":
        return True
    return "all" in doc_channels or wanted in doc_channels


# ---------------- 留痕 ----------------


def trace_step(
    step: str,
    *,
    tenant: str,
    trace_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """读步骤留痕（不写 DB、不阻塞主流程，供 observability 聚合耗时/召回/拦截）。"""
    record(step, {"tenant": tenant, "trace_id": trace_id, **(extra or {})})


async def audit_write(
    db: AsyncSession,
    *,
    tenant: str,
    actor: str,
    action: str,
    target: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """写步骤审计（audit_logs 只追加；与业务写入同事务 flush，不单独 commit）。"""
    from app.services import admin_service

    await admin_service.record_audit(
        db, tenant=tenant, actor=actor, action=action, target=target, detail=detail
    )
