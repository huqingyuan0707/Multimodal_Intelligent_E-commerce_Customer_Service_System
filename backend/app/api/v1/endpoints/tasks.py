"""任务端点框架（长任务提交/查询，对齐 API 规范 §4.5）

链路：POST /tasks → tasks 表 → GET /tasks/{id} 轮询；SSE 另有 progress/complete/error。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.responses import ok

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    """建任务请求体。"""

    type: str
    payload: dict[str, object] | None = None


@router.post("")
async def create_task(payload: CreateTaskRequest) -> dict[str, object]:
    """建任务占位。"""
    _ = payload
    return ok({"task_id": ""}, "任务框架已就绪")


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict[str, object]:
    """任务查询占位。"""
    return ok({"task_id": task_id, "status": "pending", "progress": 0}, "任务框架已就绪")
