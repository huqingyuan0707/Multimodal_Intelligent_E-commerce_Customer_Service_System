"""审批端点（/approvals：列表与批/驳，对齐 API 规范 §4.5）

链路：前端 ApprovalCenterView → 本模块 → approval_service → approvals 表。
批准时的「生效动作」（改价/改账/退款）由 approval_service.decide 派发，端点不碰业务。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])

# 审批只能由店长/运营/管理员处理（客服与仓管只能提交申请）
APPROVER_PERMS = ("shop", "ops", "admin", "*")


class ApproveRequest(BaseModel):
    """批准：可带改后参数（如审批人把 199 改成 209 再批）。"""

    modified_args: dict[str, Any] = {}
    reason: str = ""


class RejectRequest(BaseModel):
    reason: str = ""


# 审批列表可见：客服可看待办（审批中心路由含 cs），店长/仓管/运营按域令牌放行
LIST_PERMS = (
    "cs",
    "shop",
    "stock",
    "ops",
    "admin",
    "order:read",
    "order:fulfill",
    "goods:read",
    "goods:write",
    "stock:read",
    "stock:write",
)


@router.get("")
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm(*LIST_PERMS)),
    status: str = Query(default="pending", max_length=16),
    action: str = Query(default="", max_length=48),
    keyword: str = Query(default="", max_length=60),
    overdue: bool = Query(default=False),
    page: int | None = Query(default=None, ge=1),
    size: int | None = Query(default=None, ge=1, le=100),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    """审批列表（默认只看待办；带 page/size 走服务端分页，否则按 limit 返回数组兼容存量）。"""
    if page is not None or size is not None:
        data = await approval_service.list_page(
            db,
            tenant=user.tenant,
            status=status,
            action=action,
            keyword=keyword,
            overdue_only=overdue,
            page=page or 1,
            size=size or 20,
        )
        return ok(data, "获取成功")
    rows = await approval_service.list_recent(
        db, tenant=user.tenant, status=status, limit=limit or 50
    )
    return ok([approval_service.to_dict(r) for r in rows], "获取成功")


@router.get("/{approval_id}")
async def approval_detail(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm(*LIST_PERMS)),
) -> dict[str, Any]:
    """审批详情（抽屉展示用：基础字段 + 超期标记 + 政策引用；跨租户 404）。"""
    row = await approval_service.get_or_raise(db, user.tenant, approval_id)
    data = approval_service.to_dict(row)
    data["policy_refs"] = await approval_service.policy_refs(
        db, tenant=user.tenant, action=row.action
    )
    return ok(data, "获取成功")


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str,
    payload: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm(*APPROVER_PERMS)),
) -> dict[str, Any]:
    """批准并执行生效动作（改价/盘点改账/退款）。"""
    row = await approval_service.decide(
        db,
        tenant=user.tenant,
        approval_id=approval_id,
        approve=True,
        approver=user.username,
        reason=payload.reason,
        modified_args=payload.modified_args or None,
    )
    return ok(approval_service.to_dict(row), "审批已通过并生效")


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm(*APPROVER_PERMS)),
) -> dict[str, Any]:
    """驳回：账不动，原因追加留痕。"""
    row = await approval_service.decide(
        db,
        tenant=user.tenant,
        approval_id=approval_id,
        approve=False,
        approver=user.username,
        reason=payload.reason,
    )
    return ok(approval_service.to_dict(row), "已驳回，原数据保持不变")
