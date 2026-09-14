"""Agent 编排与工具注册中心端点（对齐 FRDv2 FR-3/FR-5 + API 规范 §4.12）

链路：GET /agent/tools（注册中心清单，含 Scope/Schema/超时重试/熔断态）
      → GET /agent/tools/{name}（单工具详情）→ POST /agent/tools/{name}/invoke（受控试调）
      → POST /agent/run（状态机跑一轮）→ GET /agent/runtime/{task_id}（检查点快照）
      → POST /agent/runtime/{task_id}/resume（审批后从检查点续跑）。
薄封装红线：本文件只解析入参 + 调 modules/services + ok()/fail()；
            鉴权、参数校验、超时重试、熔断全在 modules/agent 内，端点不复制一份。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import get_current_user
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.modules.agent import executor, registry, runtime
from app.modules.agent.contracts import ToolContext

router = APIRouter(prefix="/agent", tags=["agent"])


class InvokeRequest(BaseModel):
    """工具试调入参（端点私有 DTO）。"""

    args: dict[str, Any] = {}
    session_id: str = ""
    trace_id: str = ""


class RunRequest(BaseModel):
    """编排入参：tool_args 用于补规划器拿不到的业务主键（订单号/SKU 等）。"""

    query: str
    session_id: str = ""
    tool_args: dict[str, Any] = {}
    trace_id: str = ""


def _tool_view(name: str) -> dict[str, Any]:
    """工具出参 = 规格 + 当前熔断态（运维与前端同源，避免各查各的）。"""
    spec = registry.get(name)
    return {**registry.spec_to_dict(spec), "breaker": executor.breaker_snapshot(spec.name)}


@router.get("/tools")
async def list_tools(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """已注册工具清单（Agent Studio 工具页直接渲染；注册中心为空给中文提示不报错）。"""
    _ = user
    data = registry.list_tools()
    items: list[dict[str, Any]] = [
        {**item, "breaker": executor.breaker_snapshot(item["name"])} for item in data["items"]
    ]
    msg = "获取成功" if items else "暂无已注册工具，请检查启动注册"
    return ok({"total": len(items), "items": items}, msg)


@router.get("/tools/{name}")
async def get_tool(name: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """单工具详情（未注册 4005，附可用工具名便于自查）。"""
    _ = user
    return ok(_tool_view(name), "获取成功")


@router.post("/tools/{name}/invoke")
async def invoke_tool(
    name: str,
    payload: InvokeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """受控试调：策略鉴权 → 参数校验 → 熔断闸门 → 执行 → 审计（tool_calls 留痕）。

    敏感工具（refund.create）不会直接改账：返回 approval_id，账目待审批通过才动。
    """
    ctx = ToolContext(
        db=db,
        tenant=user.tenant,
        username=user.username,
        roles=list(user.roles),
        session_id=payload.session_id,
        trace_id=payload.trace_id,
    )
    data = await executor.call(ctx, name=name, args=payload.args, trace_id=payload.trace_id)
    await db.commit()
    msg = "已提交审批，待人工确认后生效" if data["approval_required"] else "调用成功"
    return ok(data, msg)


@router.post("/run")
async def run_agent(
    payload: RunRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """跑一轮编排（规则规划 → 逐步执行 → 收敛），返回终态快照与 task_id。"""
    data = await runtime.run(
        db,
        user=user,
        query=payload.query,
        session_id=payload.session_id,
        tool_args=payload.tool_args,
        trace_id=payload.trace_id,
    )
    return ok(data, f"编排结束：{data['state_label']}")


@router.get("/runtime/{task_id}")
async def get_runtime(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """编排快照（跨租户 404；检查点缺失 404 并提示不是编排任务）。"""
    return ok(await runtime.snapshot(db, tenant=user.tenant, task_id=task_id), "获取成功")


@router.post("/runtime/{task_id}/resume")
async def resume_runtime(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """审批完成后从检查点续跑（审批仍 pending 时返回 4003，不放行绕过人工）。"""
    data = await runtime.resume(db, user=user, task_id=task_id)
    return ok(data, f"续跑结束：{data['state_label']}")
