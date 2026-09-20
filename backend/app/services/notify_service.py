"""消息模板与频控服务（FR-12.2 消息与组织，对齐页面设计 §3.19）

链路：/admin 消息窗格维护模板 → 发送侧按 name 取 active 模板渲染 → core/cache 频控计数
      （键 `rl:{tenant}:notify:{user_ref}`，与对话限流同一适配层）→ 成功/失败累计到
      message_templates.reach_* → 到达率报表读它。

诚实性口径（这三条决定「这个报表能不能信」）：
- **渠道网关未接入**（短信/企微/钉钉为 P2）：send() 一律回 `delivered=false, degraded=true`，
  并把该次记账为「未送达」。不返回假成功，也不因此抛 500 —— 到达率报表会如实显示 0%，
  这正确反映了「当前确实发不出去」，而不是「接入后也发不出去」。
- 频控超限回 `1006`（与对话限流同号段），**不静默丢弃**：调用方必须知道自己被限流了。
- 风控黑名单（blocked 复核结论）买家触达回 `3007`：对已拦截用户停止自动外呼/营销触达。
- 到达率为「累计口径」（表里是累计计数，无时间窗）—— 响应里 `window_note` 如实标注，
  不做「近 30 天到达率」这种当前数据支撑不了的表述。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import cache
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import MessageTemplate
from app.db.models_admin import TEMPLATE_CHANNELS, TEMPLATE_STATUSES
from app.services import risk_service
from app.services.admin_service import dt_text, record_audit

CHANNEL_LABELS = {"sms": "短信", "wechat": "企微", "dingtalk": "钉钉", "email": "邮件"}
TEMPLATE_STATUS_LABELS = {"draft": "草稿", "active": "启用", "disabled": "已停用"}
# 网关未接入的统一说明（发送回执与报表共用同一句，避免两处措辞漂移）
GATEWAY_ABSENT_NOTE = "渠道网关未接入（短信/企微/钉钉为 P2）：本次已如实记为未送达，不冒充成功"


def split_status(raw: str) -> str:
    return (raw or "").strip()


def template_to_dict(row: MessageTemplate) -> dict[str, Any]:
    """模板出参（含累计到达口径；无发送记录时 reach_rate=None + no_data=true）。"""
    sent = int(row.reach_total or 0)
    failed = int(row.reach_failed or 0)
    delivered = max(0, sent - failed)
    return {
        "id": row.id,
        "tenant": row.tenant,
        "name": row.name,
        "channel": row.channel,
        "channel_label": CHANNEL_LABELS.get(row.channel, row.channel),
        "content": row.content,
        "status": row.status,
        "status_label": TEMPLATE_STATUS_LABELS.get(row.status, row.status),
        "sent": sent,
        "failed": failed,
        "delivered": delivered,
        "reach_rate": (round(delivered / sent, 4) if sent else None),
        "no_data": sent == 0,
        "created_at": dt_text(row.created_at),
        "updated_at": dt_text(row.updated_at),
    }


def render(content: str, user_ref: str) -> str:
    """占位符渲染（唯一支持 `{user_ref}`；未知占位符原样保留，不猜不编）。"""
    return (content or "").replace("{user_ref}", user_ref or "")


async def list_templates(
    db: AsyncSession,
    *,
    tenant: str = "",
    channel: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """模板分页（channel/status 精确过滤；非法值 1001 而不是静默回空）。"""
    if channel and channel not in TEMPLATE_CHANNELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"渠道非法：{channel}")
    if status and status not in TEMPLATE_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"模板状态非法：{status}")
    stmt = select(MessageTemplate)
    if tenant.strip():
        stmt = stmt.where(MessageTemplate.tenant == tenant.strip())
    if channel:
        stmt = stmt.where(MessageTemplate.channel == channel)
    if status:
        stmt = stmt.where(MessageTemplate.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(MessageTemplate.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [template_to_dict(row) for row in rows],
        "channels": list(TEMPLATE_CHANNELS),
        "window_note": "到达率为累计口径（无时间窗）",
    }


async def get_template_or_raise(db: AsyncSession, template_id: str) -> MessageTemplate:
    row = (
        await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "消息模板不存在", 404)
    return row


def _validate(name: str, channel: str, status: str, content: str) -> tuple[str, str, str, str]:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 64:
        raise BusinessError(ErrorCode.PARAM_INVALID, "模板名不能为空且不超过 64 字符")
    if channel not in TEMPLATE_CHANNELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"渠道非法：{channel}")
    if status not in TEMPLATE_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"模板状态非法：{status}")
    body = content or ""
    if status == "active" and not body.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "启用中的模板正文不能为空")
    return cleaned, channel, status, body


async def create_template(
    db: AsyncSession,
    *,
    tenant: str,
    name: str,
    channel: str = "sms",
    content: str = "",
    status: str = "draft",
    actor: str = "",
) -> MessageTemplate:
    """新建模板（租户内名称唯一）。"""
    cleaned_tenant = (tenant or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择模板所属租户")
    cleaned, channel, status, body = _validate(name, channel, status, content)
    existed = (
        await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.tenant == cleaned_tenant, MessageTemplate.name == cleaned
            )
        )
    ).scalar_one_or_none()
    if existed is not None:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"该租户下已存在同名模板：{cleaned}")
    row = MessageTemplate(
        tenant=cleaned_tenant,
        name=cleaned,
        channel=channel,
        content=body,
        status=status,
    )
    db.add(row)
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned_tenant,
        actor=actor,
        action="notify.template.create",
        target=cleaned,
        detail={"channel": channel, "status": status},
    )
    await db.commit()
    return row


async def update_template(
    db: AsyncSession,
    *,
    template_id: str,
    name: str,
    channel: str,
    content: str,
    status: str,
    actor: str = "",
) -> MessageTemplate:
    """改模板（名称撞同租户其他模板 1001；审计留前后状态）。"""
    row = await get_template_or_raise(db, template_id)
    cleaned, channel, status, body = _validate(name, channel, status, content)
    if cleaned != row.name:
        existed = (
            await db.execute(
                select(MessageTemplate).where(
                    MessageTemplate.tenant == row.tenant,
                    MessageTemplate.name == cleaned,
                    MessageTemplate.id != row.id,
                )
            )
        ).scalar_one_or_none()
        if existed is not None:
            raise BusinessError(ErrorCode.PARAM_INVALID, f"该租户下已存在同名模板：{cleaned}")
    before = {"name": row.name, "channel": row.channel, "status": row.status}
    row.name = cleaned
    row.channel = channel
    row.content = body
    row.status = status
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="notify.template.update",
        target=cleaned,
        detail={
            "from": before,
            "to": {"name": cleaned, "channel": channel, "status": status},
        },
    )
    await db.commit()
    return row


async def set_template_status(
    db: AsyncSession, *, template_id: str, status: str, actor: str = ""
) -> MessageTemplate:
    """启停模板（只有 active 能被发送侧使用）。"""
    if status not in TEMPLATE_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"模板状态非法：{status}")
    row = await get_template_or_raise(db, template_id)
    if status == "active" and not (row.content or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "正文为空，不能启用（发送侧会渲染出空消息）")
    old = row.status
    row.status = status
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="notify.template.status",
        target=row.name,
        detail={"from": old, "to": status},
    )
    await db.commit()
    return row


async def delete_template(db: AsyncSession, *, template_id: str, actor: str = "") -> None:
    """删除模板（破坏性操作，前端须二次确认；审计留删前口径）。"""
    row = await get_template_or_raise(db, template_id)
    detail = {"channel": row.channel, "status": row.status, "sent": int(row.reach_total or 0)}
    tenant = row.tenant
    name = row.name
    await db.delete(row)
    await db.flush()
    await record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="notify.template.delete",
        target=name,
        detail=detail,
    )
    await db.commit()


async def send(
    db: AsyncSession,
    *,
    tenant: str,
    name: str,
    user_ref: str,
    actor: str = "",
) -> dict[str, Any]:
    """按模板发送一条消息：频控 → 渲染 → 记账。

    频控超限 1006；模板不存在/未启用 1001/404；网关未接入照常记账为未送达（degraded=true）。
    返回体带 `delivered/degraded/reason`，让调用方一眼看出「这条到底送出去了没有」。
    """
    cleaned_tenant = (tenant or "").strip()
    target_ref = (user_ref or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择发送所属租户")
    if not target_ref:
        raise BusinessError(ErrorCode.PARAM_INVALID, "接收方（user_ref）不能为空")
    # 风控黑名单拦截（3007）：已拦截买家停止自动触达（防营销骚扰，放行走风控复核）。
    await risk_service.ensure_not_blocked(
        db, tenant=cleaned_tenant, user_ref=target_ref, action_label="消息触达"
    )

    row = (
        await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.tenant == cleaned_tenant,
                MessageTemplate.name == (name or "").strip(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, f"消息模板不存在：{name}", 404)
    if row.status != "active":
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"模板「{row.name}」当前为{row.status}，只有启用的模板可发送"
        )

    limit = int(settings.NOTIFY_RATE_MAX)
    window = int(settings.NOTIFY_RATE_WINDOW_SECONDS)
    key = f"rl:{cleaned_tenant}:notify:{target_ref}"
    if not await cache.allow(key, limit, window):
        hours = max(1, window // 3600)
        raise BusinessError(
            ErrorCode.RATE_LIMITED,
            f"发送过于频繁：同一接收方每 {hours} 小时最多 {limit} 条",
            429,
        )

    body = render(row.content, target_ref)
    # 网关未接入：如实记一次「未送达」，到达率因此显示真实值（而非假 100%）
    row.reach_total = int(row.reach_total or 0) + 1
    row.reach_failed = int(row.reach_failed or 0) + 1
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned_tenant,
        actor=actor,
        action="notify.send",
        target=f"{row.name}→{target_ref}",
        detail={"channel": row.channel, "delivered": False},
    )
    await db.commit()
    return {
        "template": row.name,
        "channel": row.channel,
        "channel_label": CHANNEL_LABELS.get(row.channel, row.channel),
        "user_ref": target_ref,
        "content": body,
        "delivered": False,
        "degraded": True,
        "reason": GATEWAY_ABSENT_NOTE,
        "rate_limit": {"limit": limit, "window_seconds": window},
    }


async def reach_report(db: AsyncSession, *, tenant: str = "") -> dict[str, Any]:
    """到达率报表（按模板聚合；累计口径，无发送时不编数）。"""
    stmt = select(MessageTemplate)
    if tenant.strip():
        stmt = stmt.where(MessageTemplate.tenant == tenant.strip())
    rows = list((await db.execute(stmt.order_by(MessageTemplate.name))).scalars())
    items = []
    total_sent = 0
    total_failed = 0
    for row in rows:
        item = template_to_dict(row)
        total_sent += int(item["sent"])
        total_failed += int(item["failed"])
        items.append(
            {
                "template": item["name"],
                "channel": item["channel"],
                "channel_label": item["channel_label"],
                "status": item["status"],
                "sent": item["sent"],
                "failed": item["failed"],
                "reach_rate": item["reach_rate"],
                "no_data": item["no_data"],
            }
        )
    delivered = max(0, total_sent - total_failed)
    return {
        "items": items,
        "total_sent": total_sent,
        "total_failed": total_failed,
        "total_delivered": delivered,
        "reach_rate": (round(delivered / total_sent, 4) if total_sent else None),
        "no_data": total_sent == 0,
        "window_note": "累计口径（无时间窗）；发送明细与真实网关为 P2",
        "gateway_note": GATEWAY_ABSENT_NOTE,
    }
