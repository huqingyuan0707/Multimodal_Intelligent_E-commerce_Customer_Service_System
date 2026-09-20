"""风控复核服务（拦截复核 + 关联图谱摘要，对齐 API 规范 §4.8 风控节 / 页面设计 §3.18）

链路：endpoints/risk → 本模块 → risk_events；工单中心（TicketCenter）复用既有 endpoints/tickets
      → /risk 页：风控事件表（通过/拦截）+ 协同工单。
口径：
- **禁全自动封号**：本模块只落「人工复核结论」（status + reviewer + reason），
  绝不改 users.status / 不下发封禁；拦截后的处置由人工在管理后台执行；
- 已复核事件不可重复处理（3005）；block 必填理由（1001），通过可不填；
- detail 存关联图谱摘要（同设备/同支付账号/近 30 天退款次数等），只读展示不参与判定；
- 复核写操作同步记 audit_logs（只追加不改）。
- 业务动作侧强制拦截（3007 RISK_BLOCKED）：`ensure_not_blocked` 按 (tenant, user_ref)
  查已复核 blocked 黑名单结论即拒（挂点：发券 promo_service.grant、消息触达 notify_service.send）；
  订单/售后表暂无买家 user_ref 字段（平台镜像单），下单/退款侧拦截待订单模型补买家标识后接入。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import RiskEvent
from app.db.models_biz_ops import RISK_STATUSES
from app.services import admin_service

# 状态中文化（禁止前端硬编码）
STATUS_LABELS: dict[str, str] = {"pending": "待复核", "passed": "已放行", "blocked": "已拦截"}
# 事件类型中文化（未知类型原样回显，不编标签）
KIND_LABELS: dict[str, str] = {
    "order_risk": "订单风险",
    "refund_abuse": "退款异常",
    "account_link": "账号关联",
    "coupon_abuse": "券滥用",
}


def _dt_text(value: datetime | None) -> str:
    """时间统一口径：空格秒（与订单/商品/审批一致，禁止裸 isoformat）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_detail(text: str) -> dict[str, Any]:
    """图谱摘要 JSON 解析失败按空对象处理（不让一条脏数据炸列表）。"""
    try:
        loaded = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def event_to_dict(row: RiskEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_ref": row.user_ref,
        "kind": row.kind,
        "kind_label": KIND_LABELS.get(row.kind, row.kind),
        "detail": _parse_detail(row.detail),
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "reviewable": row.status == "pending",
        "reviewer": row.reviewer,
        "reason": row.reason,
        "created_at": _dt_text(row.created_at),
    }


async def list_events(
    db: AsyncSession,
    *,
    tenant: str,
    status: str = "",
    kind: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """风控事件分页列表（status/kind 精确筛选，非法状态 1001；倒序，最新在前）。"""
    stmt = select(RiskEvent).where(RiskEvent.tenant == tenant)
    count_stmt = select(func.count()).select_from(RiskEvent).where(RiskEvent.tenant == tenant)
    if status:
        if status not in RISK_STATUSES:
            raise BusinessError(
                ErrorCode.PARAM_INVALID,
                f"风控状态非法：{status}（可选 {'/'.join(RISK_STATUSES)}）",
            )
        stmt = stmt.where(RiskEvent.status == status)
        count_stmt = count_stmt.where(RiskEvent.status == status)
    if kind.strip():
        stmt = stmt.where(RiskEvent.kind == kind.strip())
        count_stmt = count_stmt.where(RiskEvent.kind == kind.strip())
    total = int((await db.execute(count_stmt)).scalar_one())
    rows = (
        await db.execute(
            stmt.order_by(RiskEvent.created_at.desc(), RiskEvent.id)
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars()
    items = [event_to_dict(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pending": sum(1 for item in items if item["status"] == "pending"),
    }


async def _event_or_raise(db: AsyncSession, *, tenant: str, event_id: str) -> RiskEvent:
    row = (
        await db.execute(
            select(RiskEvent).where(RiskEvent.id == event_id, RiskEvent.tenant == tenant)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "风控事件不存在或无权访问", 404)
    return row


async def review_event(
    db: AsyncSession,
    *,
    tenant: str,
    event_id: str,
    block: bool,
    reason: str = "",
    reviewer: str = "",
) -> RiskEvent:
    """人工复核（仅待复核可处理）：拦截/放行均留 reviewer 与理由，不做任何封号动作。"""
    row = await _event_or_raise(db, tenant=tenant, event_id=event_id)
    if row.status != "pending":
        raise BusinessError(
            ErrorCode.ORDER_STATE_ILLEGAL,
            f"该事件已「{STATUS_LABELS.get(row.status, row.status)}」，不可重复复核",
        )
    text = reason.strip()
    if block and not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "拦截必须填写理由（合规留痕）")
    row.status = "blocked" if block else "passed"
    row.reviewer = reviewer
    row.reason = text
    await db.flush()
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=reviewer,
        action="risk.block" if block else "risk.pass",
        target=row.id,
        detail={"user_ref": row.user_ref, "kind": row.kind, "reason": text},
    )
    await db.commit()
    return row


async def ensure_not_blocked(
    db: AsyncSession, *, tenant: str, user_ref: str, action_label: str
) -> None:
    """业务动作侧强制拦截（3007 黑名单口径）：该买家存在已复核 blocked 结论即拒。

    口径（FRD FR-10.8「拦截 → 人工复核 → 黑名单/放行」）：
    - 只拦已复核 `blocked` 的事件（黑名单结论）；`pending` 是疑似不拦（转人工，不误伤正常买家）；
    - 本守卫只拒动作、不发任何处置（禁全自动封号红线不变），放行/处置走风控复核人工流程。
    """
    ref = (user_ref or "").strip()
    if not ref:
        return
    hit = (
        await db.execute(
            select(RiskEvent.id)
            .where(
                RiskEvent.tenant == tenant,
                RiskEvent.user_ref == ref,
                RiskEvent.status == "blocked",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if hit is not None:
        raise BusinessError(
            ErrorCode.RISK_BLOCKED,
            f"该买家已被风控拦截（黑名单），{action_label}已拒绝；如需放行请走风控复核流程",
        )
