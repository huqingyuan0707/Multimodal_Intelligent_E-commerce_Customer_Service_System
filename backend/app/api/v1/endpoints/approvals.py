"""审批端点框架（敏感动作批/驳，对齐 API 规范 §4.5）

链路：POST /approvals/{id}/approve|reject → service → Runtime 恢复。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.responses import ok

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApproveRequest(BaseModel):
    """审批请求体（改参重试字段后续补）。"""

    modified_args: dict[str, object] | None = None


class RejectRequest(BaseModel):
    """驳回请求体。"""

    reason: str = ""


@router.get("")
async def list_approvals() -> dict[str, object]:
    """待办列表占位。"""
    return ok([], "审批框架已就绪")


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, payload: ApproveRequest) -> dict[str, object]:
    """批准占位。"""
    _ = payload
    return ok({"id": approval_id}, "审批框架已就绪")


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, payload: RejectRequest) -> dict[str, object]:
    """驳回占位。"""
    _ = payload
    return ok({"id": approval_id}, "审批框架已就绪")
