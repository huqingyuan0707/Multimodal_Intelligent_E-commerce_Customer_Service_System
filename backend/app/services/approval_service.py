"""审批服务（改价 / 盘点差异 / 超阈值退款恒进审批，对齐 API 规范 §4.5、数据模型文档 §2.1）

链路：goods/inventory/order_service.create() → 本模块落 approvals 表；
      endpoints/approvals → decide() → _apply() 按 action 派发到域服务生效函数。
循环依赖口径：域服务在模块级 import 本模块创建审批；本模块只在 _apply() 内**延迟 import**
             域服务，避免模块级循环导入（改价/盘点/退款的生效逻辑留在各自域服务里）。
红线：审批单不可重复处理；未通过的申请绝不改账（改价前后 SKU 价格由 decide 才落库）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Approval, KbDoc

# 审批类型中文化（审批中心展示用，禁止前端硬编码）
ACTION_LABELS: dict[str, str] = {
    "sku.price_change": "SKU 改价",
    "inventory.stocktake_diff": "盘点差异",
    "inventory.replenish": "补货需求",
    "order.refund": "退款",
    "aftersale.scrap": "售后报损",
}

# 审批类型 → 政策引用检索关键词（详情抽屉「政策引用」行，同租户知识库标题模糊找 Top3）
ACTION_POLICY_KEYWORDS: dict[str, list[str]] = {
    "order.refund": ["退货", "退款", "无理由"],
    "sku.price_change": ["改价", "价格"],
    "inventory.stocktake_diff": ["盘点", "库存"],
    "inventory.replenish": ["补货", "采购"],
    "aftersale.scrap": ["报损", "质检", "退货"],
}

STATUS_LABELS: dict[str, str] = {"pending": "待审批", "approved": "已通过", "rejected": "已驳回"}


def _parse_args(row: Approval) -> dict[str, Any]:
    """args 列是 JSON 文本，解析失败按空参数处理（不让脏数据炸列表）。"""
    try:
        loaded = json.loads(row.args or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def waiting_hours(row: Approval) -> float:
    """已等待小时（创建时间距今；脏时间按 0 处理，不断渲染）。"""
    if row.created_at is None:
        return 0.0
    delta = datetime.now(UTC).replace(tzinfo=None) - row.created_at.replace(tzinfo=None)
    return round(max(0.0, delta.total_seconds() / 3600), 1)


def is_overdue(row: Approval) -> bool:
    """是否超期未处理（待办且等待超 APPROVAL_SLA_HOURS；超时升级的展示口径）。"""
    return row.status == "pending" and waiting_hours(row) > settings.APPROVAL_SLA_HOURS


def overdue_cutoff() -> datetime:
    """超期分界创建时间（naive UTC，与落库口径一致，供列表筛选）。"""
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=settings.APPROVAL_SLA_HOURS)


def to_dict(row: Approval) -> dict[str, Any]:
    """审批单出参（前端 ApprovalCenter 直接渲染，含中文标签）。"""
    return {
        "id": row.id,
        "action": row.action,
        "action_label": ACTION_LABELS.get(row.action, row.action),
        "target": row.target,
        "args": _parse_args(row),
        "reason": row.reason,
        "applicant": row.applicant,
        "approver": row.approver,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "session_id": row.session_id,
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        "decided_at": (
            row.decided_at.isoformat(sep=" ", timespec="seconds") if row.decided_at else ""
        ),
        "waiting_hours": waiting_hours(row),
        "overdue": is_overdue(row),
    }


async def create(
    db: AsyncSession,
    *,
    tenant: str,
    action: str,
    target: str,
    args: dict[str, Any],
    reason: str,
    applicant: str,
    session_id: str = "",
) -> Approval:
    """落一条待审记录（敏感动作不直接生效）。

    只 flush 不 commit：与调用方的业务写入同事务，避免「审批已建、账未动」的半提交。
    """
    row = Approval(
        tenant=tenant,
        action=action,
        target=target,
        args=json.dumps(args, ensure_ascii=False),
        reason=reason,
        applicant=applicant,
        session_id=session_id,
    )
    db.add(row)
    await db.flush()
    return row


async def get_or_raise(db: AsyncSession, tenant: str, approval_id: str) -> Approval:
    """按租户取审批单，取不到 1004（越权与不存在同口径，不泄漏他租户数据）。"""
    row = (
        await db.execute(
            select(Approval).where(Approval.tenant == tenant, Approval.id == approval_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "审批单不存在或无权访问", 404)
    return row


async def list_recent(
    db: AsyncSession, *, tenant: str, status: str = "", limit: int = 50
) -> list[Approval]:
    """审批列表（默认待办优先，按创建时间倒序；存量兼容口径，新代码走 list_page）。"""
    stmt = select(Approval).where(Approval.tenant == tenant)
    if status:
        stmt = stmt.where(Approval.status == status)
    rows = (
        (await db.execute(stmt.order_by(Approval.created_at.desc()).limit(limit))).scalars().all()
    )
    return list(rows)


# ---------------- 分页列表（审批中心服务端分页口径） ----------------


def _apply_filters(stmt, *, status: str = "", action: str = "", keyword: str = ""):
    """列表筛选：状态精确 + 类型精确 + 关键字模糊（对象/申请人/原因）。"""
    if status:
        stmt = stmt.where(Approval.status == status)
    if action:
        stmt = stmt.where(Approval.action == action)
    key = keyword.strip()
    if key:
        like = f"%{key}%"
        stmt = stmt.where(
            (Approval.target.like(like))
            | (Approval.applicant.like(like))
            | (Approval.reason.like(like))
        )
    return stmt


async def list_page(
    db: AsyncSession,
    *,
    tenant: str,
    status: str = "",
    action: str = "",
    keyword: str = "",
    overdue_only: bool = False,
    page: int = 1,
    size: int = 20,
) -> dict:
    """审批分页列表（服务端分页默认 20，供审批中心直连；总数一次带出）。"""
    if status and status not in STATUS_LABELS:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"审批状态非法：{status}（可选 {'/'.join(STATUS_LABELS)}，空=全部）",
        )
    stmt = _apply_filters(
        select(Approval).where(Approval.tenant == tenant),
        status=status,
        action=action,
        keyword=keyword,
    )
    if overdue_only:
        stmt = stmt.where(Approval.status == "pending", Approval.created_at < overdue_cutoff())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Approval.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "items": [to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "size": size,
    }


async def _apply(
    db: AsyncSession, *, tenant: str, action: str, args: dict[str, Any], actor: str
) -> None:
    """审批通过后的生效动作，派发到域服务（延迟 import 避开循环依赖）。"""
    if action == "sku.price_change":
        from app.services import goods_service

        await goods_service.apply_price_change(db, tenant=tenant, args=args, actor=actor)
        return
    if action == "inventory.stocktake_diff":
        from app.services import inventory_service

        await inventory_service.apply_stocktake(db, tenant=tenant, args=args, actor=actor)
        return
    if action == "order.refund":
        from app.services import order_service

        await order_service.apply_refund(db, tenant=tenant, args=args, actor=actor)
        return
    if action == "aftersale.scrap":
        from app.services import order_service

        await order_service.apply_scrap(db, tenant=tenant, args=args, actor=actor)
        return
    if action == "inventory.replenish":
        # 采购单在 P2（/purchase）落地：此处仅确认审批通过，不产生库存变动。
        return
    raise BusinessError(ErrorCode.PARAM_INVALID, f"未知审批类型：{action}")


async def policy_refs(db: AsyncSession, *, tenant: str, action: str, limit: int = 3) -> list[dict]:
    """政策引用：按审批类型关键词在同租户知识库标题里模糊找 TopN（详情抽屉展示用）。

    无命中/未知类型返回空数组不断渲染；只读 kb_docs 标题+id，不读正文。
    """
    seen: set[str] = set()
    refs: list[dict] = []
    for keyword in ACTION_POLICY_KEYWORDS.get(action, []):
        if len(refs) >= limit:
            break
        rows = (
            await db.execute(
                select(KbDoc)
                .where(KbDoc.tenant == tenant, KbDoc.title.like(f"%{keyword}%"))
                .order_by(KbDoc.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        for doc in rows:
            if doc.id not in seen:
                seen.add(doc.id)
                refs.append({"id": doc.id, "title": doc.title})
            if len(refs) >= limit:
                break
    return refs


async def decide(
    db: AsyncSession,
    *,
    tenant: str,
    approval_id: str,
    approve: bool,
    approver: str,
    reason: str = "",
    modified_args: dict[str, Any] | None = None,
) -> Approval:
    """批/驳：批准则先执行生效动作再改状态（同事务，失败整体回滚）。"""
    row = await get_or_raise(db, tenant, approval_id)
    if row.status != "pending":
        raise BusinessError(
            ErrorCode.APPROVAL_DENIED,
            f"该审批已是「{STATUS_LABELS.get(row.status, row.status)}」，不能重复处理",
        )
    if not approve and not reason.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "驳回理由必填，请填写后再驳回", 400)
    args = _parse_args(row)
    if approve and modified_args:
        args.update(modified_args)
    if approve:
        await _apply(db, tenant=tenant, action=row.action, args=args, actor=approver)
        row.status = "approved"
        if reason.strip():
            row.reason = f"{row.reason}｜批准说明：{reason.strip()}"[:200]
    else:
        row.status = "rejected"
        if reason.strip():
            row.reason = f"{row.reason}｜驳回原因：{reason.strip()}"[:200]
    row.approver = approver
    row.decided_at = datetime.now(UTC).replace(tzinfo=None)
    # 批/驳同步记审计（只 flush，与审批同事务；审批中心可回溯谁何时动了哪单）
    from app.services import admin_service

    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=approver,
        action="approval.approve" if approve else "approval.reject",
        target=row.id,
        detail={"action": row.action, "target": row.target, "status": row.status},
    )
    await db.commit()
    return row
