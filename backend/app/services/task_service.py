"""任务服务（前置地基：真实落库，对齐 API 规范 §4.5 + 数据模型文档 §2）

链路：endpoints/tasks 薄封装 → 本模块 → tasks 表 → GET 轮询/SSE progress。
红线：所有查询强制按 tenant 过滤；列表再按 username 收敛到本人，单查按 tenant 校验归属。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Task


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def task_to_dict(row: Task) -> dict[str, Any]:
    return {
        "task_id": row.id,
        "id": row.id,
        "type": row.type,
        "status": row.status,
        "progress": row.progress,
        "result": _parse_json(row.output, {}),
        "error": _parse_json(row.error, {}),
        "created_at": _dt_text(row.created_at),
        "updated_at": _dt_text(row.updated_at),
    }


async def create_task(
    db: AsyncSession,
    *,
    tenant: str,
    username: str,
    type: str,
    payload: dict[str, Any] | None = None,
) -> Task:
    """建任务（类型必填；payload 存 input JSON，状态 pending，进度 0）。"""
    cleaned = (type or "").strip()
    if not cleaned:
        raise BusinessError(ErrorCode.PARAM_INVALID, "任务类型不能为空")
    row = Task(
        tenant=tenant,
        username=username,
        type=cleaned[:48],
        status="pending",
        progress=0,
        input=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(row)
    await db.commit()
    return row


async def mark_task(
    db: AsyncSession,
    *,
    tenant: str,
    task_id: str,
    status: str,
    progress: float = 0.0,
    output: dict[str, Any] | None = None,
    error: str = "",
) -> Task:
    """后台执行体专用：推进度/落结果（跨租户 404；调用方保证幂等语义）。"""
    row = await get_task(db, tenant=tenant, task_id=task_id)
    row.status = status
    row.progress = progress
    if output is not None:
        row.output = json.dumps(output, ensure_ascii=False)
    if error:
        row.error = json.dumps({"message": error}, ensure_ascii=False)
    await db.commit()
    return row


async def get_task(db: AsyncSession, *, tenant: str, task_id: str) -> Task:
    """单查（跨租户 404 不泄露存在性）。"""
    row = (
        await db.execute(select(Task).where(Task.id == task_id, Task.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.TASK_NOT_FOUND, "任务不存在或已过期", 404)
    return row


async def list_tasks(
    db: AsyncSession,
    *,
    tenant: str,
    username: str,
    page: int = 1,
    size: int = 20,
    status: str = "",
) -> list[dict[str, Any]]:
    """任务列表（本人维度倒序；page/size 默认 20，暂返回数组保持前端兼容）。"""
    stmt = (
        select(Task)
        .where(Task.tenant == tenant, Task.username == username)
        .order_by(Task.created_at.desc())
    )
    if (status or "").strip():
        stmt = stmt.where(Task.status == status.strip())
    stmt = stmt.offset((page - 1) * size).limit(size)
    rows = list((await db.execute(stmt)).scalars())
    return [task_to_dict(r) for r in rows]
