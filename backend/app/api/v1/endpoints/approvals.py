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


@router.get("")
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("order:read", "goods:write", "stock:write")),
    status: str = Query(default="pending", max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """审批列表（默认只看待办）。"""
    rows = await approval_service.list_recent(db, tenant=user.tenant, status=status, limit=limit)
    return ok([approval_service.to_dict(r) for r in rows], "获取成功")


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
