"""业务连接器（FRDv2 附录 A 其余 6 个工具：order / logistics / stock / coupon / kb / refund + 回流建单）

链路：bootstrap.register_builtin() → registry.register(本方 ToolSpec)
      → executor.call → handler(ctx, args) → 对应 services 域服务（不直连表、不复制业务规则）。
口径：
- 连接器只做「薄适配 + 入参出参整形」，状态机 / 金额 / 库存口径全部留在 services，
  改规则只改一处（避免两套真相）。
- refund.create 标 requires_approval=True：调用即落审批单、订单状态不变，
  由 approval_service.decide 通过后才执行 apply_refund（FR-7 恒送审，账不动）。
- ticket.create 是联动模式②（office-agent 回流）的写入口：审批闸门唯一在对端，
  本侧经网关直接执行，幂等口径由 idem_key 闭环（同键重放返回原单，绝不双单）。
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import BusinessError, ErrorCode
from app.modules.agent.contracts import ToolContext, ToolSpec
from app.modules.agent.registry import register
from app.services import (
    inventory_service,
    knowledge_service,
    logistics_service,
    order_service,
    promo_service,
    review_service,
)

# ---------------- 附录 A 工具契约（Scope 与入参口径与规范逐条对齐） ----------------


async def _order_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """订单查询（附录 A：必校验订单归属——租户过滤在 _get_order 内，跨租户同 404）。"""
    detail = await order_service.get_detail(
        ctx.db, tenant=ctx.tenant, order_id=str(args["order_id"]).strip()
    )
    return {
        "order_id": detail["id"],
        "outer_id": detail["outer_id"],
        "platform": detail["platform"],
        "status": detail["status"],
        "status_label": detail["status_label"],
        "total": detail["total"],
        "items": detail["items"],
        "tracking_no": detail.get("tracking_no", ""),
        "company": detail.get("company", ""),
        "trace_id": detail.get("trace_id", ""),
    }


async def _logistics_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """物流追踪（节点卡片数据源）：先取订单面单，再查轨迹；未发货给明确中文提示。"""
    detail = await order_service.get_detail(
        ctx.db, tenant=ctx.tenant, order_id=str(args["order_id"]).strip()
    )
    tracking_no = str(detail.get("tracking_no") or "").strip()
    if not tracking_no:
        raise BusinessError(ErrorCode.NOT_FOUND, "该订单还没有物流单号，可能尚未发货", 404)
    return await logistics_service.track(ctx.db, tenant=ctx.tenant, tracking_no=tracking_no)


async def _stock_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """库存查询（可用量口径恒为「在库 − 预占 − 锁定」，由 inventory_service 统一算）。"""
    size = str(args.get("size", "") or "").strip()
    table = await inventory_service.stock_table(
        ctx.db, tenant=ctx.tenant, sku_id=str(args["sku_id"]).strip(), size=200
    )
    rows = list(table["items"])
    if size:
        rows = [row for row in rows if str(row.get("size", "")) == size]
    available = sum(int(row.get("available", 0)) for row in rows)
    return {
        "sku_id": str(args["sku_id"]).strip(),
        "size": size,
        "available": available,
        "warehouse_count": len(rows),
        "warning": any(bool(row.get("warning")) for row in rows),
        "items": rows,
    }


async def _coupon_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """优惠/活动查询（客服按话术模板介绍，发券动作不在此工具内——资损动作单独审批）。"""
    rows = await promo_service.list_promos(ctx.db, tenant=ctx.tenant)
    items = [promo_service.promo_to_dict(row) for row in rows]
    if bool(args.get("only_active", True)):
        items = [item for item in items if item.get("status") == "active"]
    return {"total": len(items), "items": items}


async def _kb_retrieve(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """知识库检索（唯一权威来源）：走在线治理链路，密级/生效期/渠道过滤在 service 内。"""
    query = str(args["query"]).strip()
    refs = await knowledge_service.retrieve(
        query,
        ctx.tenant,
        top_k=args.get("top_k"),
        db=ctx.db,
        roles=ctx.roles,
        trace_id=ctx.trace_id,
    )
    return {"query": query, "total": len(refs), "references": refs}


async def _refund_create(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """退款申请（敏感）：只落售后单与审批单，**账不动**；批准后才 apply_refund 生效。

    force_approval=True 是 Agent 侧恒送审口径：AI 发起的退款不看金额一律进审批，
    与人工后台的「超阈值才审批」并存（两套入口两种风险等级，规则各自写在归属层）。
    """
    return await order_service.create_aftersale(
        ctx.db,
        tenant=ctx.tenant,
        order_id=str(args["order_id"]).strip(),
        reason=str(args["reason"]).strip(),
        amount=int(args["amount"]),
        trace_id=ctx.trace_id,
        applicant=ctx.username,
        force_approval=True,
    )


async def _ticket_create(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """回流建单（联动模式②）：审批闸门在对端，本侧幂等执行——同 idem_key 重放返回原单。

    出参带 replayed 标记：对端审计据此区分「本次生效」与「幂等回放」，不双单口径可验证。
    """
    ticket, replayed = await review_service.create_ticket_idempotent(
        ctx.db,
        tenant=ctx.tenant,
        idem_key=str(args["idem_key"]).strip(),
        kind=str(args["kind"]).strip(),
        source_ref=str(args.get("source_ref") or "").strip(),
        assignee=str(args.get("assignee") or "").strip(),
        sla_hours=int(args.get("sla_hours") or 48),
    )
    return {
        "ticket_id": ticket.id,
        "kind": ticket.kind,
        "source_ref": ticket.source_ref,
        "assignee": ticket.assignee,
        "status": ticket.status,
        "sla_due": (
            ticket.sla_due.isoformat(sep=" ", timespec="seconds") if ticket.sla_due else ""
        ),
        "idem_key": ticket.idem_key or "",
        "replayed": replayed,
        "created_by": ctx.username,
    }


# ---------------- 规格声明（params 即对外契约，Agent Studio 直接渲染） ----------------

_ORDER_ID = {
    "type": "string",
    "title": "订单号",
    "minLength": 1,
    "maxLength": 40,
}

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="order.query",
        scope="order:read",
        description="查询订单状态、明细、金额与售后记录（必校验订单归属）",
        params={
            "type": "object",
            "properties": {"order_id": _ORDER_ID},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        handler=_order_query,
    ),
    ToolSpec(
        name="logistics.query",
        scope="order:read",
        description="查询订单物流轨迹与预计到达（节点卡片数据源）",
        params={
            "type": "object",
            "properties": {"order_id": _ORDER_ID},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        handler=_logistics_query,
    ),
    ToolSpec(
        name="stock.query",
        scope="stock:read",
        description="按 SKU 查询可用库存（可用 = 在库 − 预占 − 锁定，可再按尺码过滤）",
        params={
            "type": "object",
            "properties": {
                "sku_id": {"type": "string", "title": "SKU ID", "minLength": 1, "maxLength": 40},
                "size": {"type": "string", "title": "尺码", "maxLength": 20},
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
        handler=_stock_query,
    ),
    ToolSpec(
        name="coupon.query",
        scope="promo:read",
        description="查询本租户在售优惠活动与剩余预算（只读，发券须走审批）",
        params={
            "type": "object",
            "properties": {"only_active": {"type": "boolean", "title": "只看进行中"}},
            "additionalProperties": False,
        },
        handler=_coupon_query,
    ),
    ToolSpec(
        name="kb.retrieve",
        scope="kb:read",
        description="检索企业知识库（唯一权威来源，带密级/生效期/渠道治理过滤）",
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "title": "检索问题", "minLength": 1, "maxLength": 200},
                "top_k": {"type": "integer", "title": "召回条数", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_kb_retrieve,
    ),
    ToolSpec(
        name="refund.create",
        scope="trade:refund",
        description="发起退款申请（敏感操作：调用即进审批，账不动，批准后才生效）",
        params={
            "type": "object",
            "properties": {
                "order_id": _ORDER_ID,
                "amount": {"type": "integer", "title": "退款金额（分）", "minimum": 1},
                "reason": {"type": "string", "title": "退款原因", "minLength": 1, "maxLength": 200},
            },
            "required": ["order_id", "amount", "reason"],
            "additionalProperties": False,
        },
        handler=_refund_create,
        idempotent=False,  # 资金动作绝不自动重试
        requires_approval=True,
        approval_action="order.refund",
    ),
    ToolSpec(
        name="ticket.create",
        scope="ticket:write",
        description=(
            "回流创建协同工单（联动模式②：审批闸门在对端，本侧直接执行；"
            "idem_key 必填，同键重放返回原单绝不双单）"
        ),
        params={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "title": "工单类型", "minLength": 1, "maxLength": 32},
                "source_ref": {"type": "string", "title": "来源关联", "maxLength": 64},
                "assignee": {"type": "string", "title": "处理人", "maxLength": 64},
                "sla_hours": {"type": "integer", "title": "SLA 小时", "minimum": 1, "maximum": 720},
                "idem_key": {
                    "type": "string",
                    "title": "幂等键",
                    "minLength": 8,
                    "maxLength": 64,
                },
            },
            "required": ["kind", "idem_key"],
            "additionalProperties": False,
        },
        handler=_ticket_create,
        idempotent=True,  # 幂等键回放就绪：可重试、可重放，同键绝不双单
    ),
)


def register_all() -> list[str]:
    """装载全部连接器（幂等，重复调用只覆盖同规格注册项）。"""
    for spec in SPECS:
        register(spec)
    return [spec.name for spec in SPECS]


def self_check() -> list[str]:
    """启动自检：规格自洽（Scope / Schema 形状 / required 与 properties 对齐 / 审批声明）。

    返回中文问题列表（空=健康）。只告警不阻断启动，问题会写进日志便于定位。
    """
    problems: list[str] = []
    seen: set[str] = set()
    for spec in SPECS:
        if spec.name in seen:
            problems.append(f"工具名重复：{spec.name}")
        seen.add(spec.name)
        if not spec.scope:
            problems.append(f"{spec.name} 缺 Scope")
        if spec.params.get("type") != "object":
            problems.append(f"{spec.name} 入参 Schema 必须是 object")
        props = spec.params.get("properties")
        prop_keys = set(props) if isinstance(props, dict) else set()
        required = spec.params.get("required")
        for key in required if isinstance(required, list) else []:
            if key not in prop_keys:
                problems.append(f"{spec.name} 的 required「{key}」未在 properties 中声明")
        if spec.requires_approval and not spec.approval_action:
            problems.append(f"{spec.name} 需审批但未声明 approval_action")
    return problems
