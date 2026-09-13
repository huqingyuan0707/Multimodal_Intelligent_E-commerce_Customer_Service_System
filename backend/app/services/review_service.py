"""评价与工单服务（对齐 FRD FR-10.8/FR-12.3/附录 D/F + API 规范 §4.8）

链路：endpoints/reviews|tickets → 本模块 → reviews/tickets（差评 ticket_id 双向可跳）。
红线：工单关闭结论必填；SLA 逾期由查询方计算展示，不在此处定时。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Review, Ticket

REVIEW_LEVELS = ("good", "mid", "bad")
TICKET_STATUSES = ("open", "doing", "closed")


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def _dt_text(value) -> str:
    """时间统一口径：空格秒（与订单/商品/审批一致，禁止裸 isoformat）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def review_to_dict(row: Review) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform": row.platform,
        "outer_id": row.outer_id,
        "level": row.level,
        "content": row.content,
        "tags": _parse_json(row.tags, []),
        "replied": row.replied,
        "reply": row.reply,
        "ticket_id": row.ticket_id,
        "created_at": _dt_text(row.created_at),
    }


def ticket_to_dict(row: Ticket) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "source_ref": row.source_ref,
        "assignee": row.assignee,
        "sla_due": _dt_text(row.sla_due),
        "status": row.status,
        "conclusion": row.conclusion,
        "created_at": _dt_text(row.created_at),
    }


async def create_review(
    db: AsyncSession,
    *,
    tenant: str,
    platform: str,
    outer_id: str,
    level: str,
    content: str,
    tags: list[str] | None = None,
) -> Review:
    """评价入库（平台同步/手工补录；差评后续建工单跟进）。"""
    if level not in REVIEW_LEVELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, "评价等级非法")
    row = Review(
        tenant=tenant,
        platform=platform,
        outer_id=outer_id,
        level=level,
        content=content,
        tags=json.dumps(tags or [], ensure_ascii=False),
    )
    db.add(row)
    await db.flush()
    return row


async def list_reviews(
    db: AsyncSession, *, tenant: str, level: str = "", limit: int = 50
) -> list[Review]:
    """评价列表（level=bad 看差评盘）。"""
    stmt = select(Review).where(Review.tenant == tenant).order_by(Review.created_at.desc())
    if level:
        stmt = stmt.where(Review.level == level)
    rows = (await db.execute(stmt.limit(max(1, min(limit, 200))))).scalars().all()
    return list(rows)


async def reply_review(db: AsyncSession, *, tenant: str, review_id: str, reply: str) -> Review:
    """评价回复（置 replied，后续补话术模板校验）。"""
    row = (
        await db.execute(select(Review).where(Review.id == review_id, Review.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "评价不存在")
    if not reply.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "回复内容不能为空")
    row.reply = reply.strip()
    row.replied = True
    await db.flush()
    return row


async def create_ticket(
    db: AsyncSession,
    *,
    tenant: str,
    kind: str,
    source_ref: str,
    assignee: str = "",
    sla_hours: int = 48,
) -> Ticket:
    """建协同工单（SLA 默认 48h；差评建单 sla_hours 传 2）。"""
    row = Ticket(
        tenant=tenant,
        kind=kind,
        source_ref=source_ref,
        assignee=assignee,
        sla_due=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=sla_hours),
    )
    db.add(row)
    await db.flush()
    return row


async def create_review_ticket(
    db: AsyncSession, *, tenant: str, review_id: str, assignee: str = ""
) -> tuple[Ticket, Review]:
    """差评一键建工单（ticket_id 回写评价，双向可跳）。"""
    row = (
        await db.execute(select(Review).where(Review.id == review_id, Review.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "评价不存在")
    if row.ticket_id:
        existed = (
            await db.execute(select(Ticket).where(Ticket.id == row.ticket_id))
        ).scalar_one_or_none()
        if existed is not None:
            return existed, row
    ticket = await create_ticket(
        db, tenant=tenant, kind="review", source_ref=row.id, assignee=assignee, sla_hours=2
    )
    row.ticket_id = ticket.id
    await db.flush()
    return ticket, row


async def list_tickets(
    db: AsyncSession, *, tenant: str, status: str = "", limit: int = 50
) -> list[Ticket]:
    """工单列表（状态过滤；逾期由前端按 sla_due 算红条）。"""
    stmt = select(Ticket).where(Ticket.tenant == tenant).order_by(Ticket.created_at.desc())
    if status:
        if status not in TICKET_STATUSES:
            raise BusinessError(ErrorCode.PARAM_INVALID, "工单状态非法")
        stmt = stmt.where(Ticket.status == status)
    rows = (await db.execute(stmt.limit(max(1, min(limit, 200))))).scalars().all()
    return list(rows)


async def transfer_ticket(
    db: AsyncSession, *, tenant: str, ticket_id: str, assignee: str
) -> Ticket:
    """工单转交（已关闭不可转）。"""
    row = await _get_ticket(db, tenant=tenant, ticket_id=ticket_id)
    if row.status == "closed":
        raise BusinessError(ErrorCode.PARAM_INVALID, "已关闭工单不可转交")
    row.assignee = assignee
    if row.status == "open":
        row.status = "doing"
    await db.flush()
    return row


async def close_ticket(db: AsyncSession, *, tenant: str, ticket_id: str, conclusion: str) -> Ticket:
    """工单关闭（结论必填，回填沉淀知识；已关闭不可重关）。"""
    if not conclusion.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "关闭结论不能为空")
    row = await _get_ticket(db, tenant=tenant, ticket_id=ticket_id)
    if row.status == "closed":
        raise BusinessError(ErrorCode.PARAM_INVALID, "工单已关闭")
    row.conclusion = conclusion.strip()
    row.status = "closed"
    await db.flush()
    return row


async def _get_ticket(db: AsyncSession, *, tenant: str, ticket_id: str) -> Ticket:
    row = (
        await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "工单不存在")
    return row
