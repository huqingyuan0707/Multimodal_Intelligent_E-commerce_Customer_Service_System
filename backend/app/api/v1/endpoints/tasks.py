"""任务端点（真实落库 + 后台执行，对齐 API 规范 §4.5）

链路：POST /tasks → task_service 建行 → BackgroundTasks 分发执行 → GET /tasks/{id} 轮询；
SSE 另有 progress/complete/error。列表按本人隔离倒序，page/size 默认 20。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import get_current_user
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    """建任务请求体。"""

    type: str
    payload: dict[str, Any] | None = None


@router.get("")
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default="", max_length=16),
) -> dict[str, Any]:
    """任务列表（本人维度；真实空数据 [] 不报错）。"""
    items = await task_service.list_tasks(
        db, tenant=user.tenant, username=user.username, page=page, size=size, status=status
    )
    return ok(items, "获取成功")


@router.post("")
async def create_task(
    payload: CreateTaskRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """建任务（落库 pending 行即返 task_id；后台按类型分发执行，轮询看 running→done）。"""
    row = await task_service.create_task(
        db, tenant=user.tenant, username=user.username, type=payload.type, payload=payload.payload
    )
    background.add_task(
        task_service.run_direct_task,
        tenant=user.tenant,
        task_id=row.id,
        type=row.type,
        payload=payload.payload,
    )
    return ok({"task_id": row.id}, "任务已提交")


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """任务查询（跨租户 404）。"""
    row = await task_service.get_task(db, tenant=user.tenant, task_id=task_id)
    return ok(task_service.task_to_dict(row), "获取成功")
