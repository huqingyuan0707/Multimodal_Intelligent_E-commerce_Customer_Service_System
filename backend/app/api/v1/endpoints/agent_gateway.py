"""外部 Agent 拉取出口（/api/v1/agent-gateway/*，对齐仓库联动方案 §7「数据不出域」）

链路：外部 Agent（office-agent）联动层 → POST /agent-gateway/invoke
      → 服务账号鉴权（require_perm）→ 采纳 X-On-Behalf-Of（白名单）→ executor.call
      → ok(data)；trace 由 TraceMiddleware 注入并随信封回传，端点不自造。

为什么出口必须复用 executor.call 而不是让对端直调各业务 REST：
连接器不是裸 REST（logistics.query 要先解运单号、stock.query 要按尺码过滤、
coupon.query 有 active 过滤），复用内核即「超时/重试/熔断/Schema 校验/审计」一套口径，
否则业务规则会在第二处复制出两套真相。

红线：
- tenant/roles 一律取 Token，绝不取请求体——对端只能看到自己租户的数据；
- X-On-Behalf-Of 仅当 Token 的 sub 命中服务账号白名单才采纳，其余主体带该头一律
  忽略并告警（否则等于把审计发起人交给调用方随便填）；
- 网关只做「解析入参 + 调内核 + 包信封」，不复制任何业务判断。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.middleware import current_trace_id
from app.core.rbac import require_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser, set_on_behalf_of
from app.db.session import get_db
from app.modules.agent import executor, registry
from app.modules.agent.contracts import ToolContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-gateway", tags=["agent-gateway"])


class GatewayInvokeRequest(BaseModel):
    """出站调用入参（对端 linkage 层固定形状：工具名 + 入参原样透传）。

    这里**不收** tenant/username/roles：身份只认 Token，参数位就是权限位。
    """

    tool: str
    args: dict[str, Any] = {}


async def gateway_identity(
    request: Request,
    user: CurrentUser = Depends(require_perm(settings.OFFICE_AGENT_GATEWAY_PERM)),
) -> CurrentUser:
    """网关身份校验：服务账号令牌放行，并按白名单决定是否采纳 X-On-Behalf-Of。"""
    claimed = (request.headers.get("x-on-behalf-of") or "").strip()
    if not claimed:
        return user
    if user.username in settings.OFFICE_AGENT_SERVICE_ACCOUNTS:
        set_on_behalf_of(claimed)
        return user
    logger.warning(
        "忽略非白名单主体 %s 透传的 X-On-Behalf-Of=%s（防止伪造审计发起人）",
        user.username,
        claimed,
    )
    return user


@router.post("/invoke")
async def invoke_tool(
    payload: GatewayInvokeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(gateway_identity),
) -> dict[str, Any]:
    """受控外调：Scope 鉴权 → Schema 校验 → 熔断闸门 → 执行 → 审计，与内部试调同一内核。

    失败（业务拒绝/上游异常）由 main.py 统一转 fail() 信封，本端点不写业务分支。
    """
    trace = current_trace_id()
    ctx = ToolContext(
        db=db,
        tenant=user.tenant,
        username=user.username,
        roles=list(user.roles),
        trace_id=trace,
    )
    try:
        data = await executor.call(ctx, name=payload.tool, args=payload.args, trace_id=trace)
    finally:
        # 成败都提交：内核好坏两条路径都写审计，失败一次就丢一条留痕等于跨系统审计断链
        # （同一 trace 要在两侧都可查，排障才有意义）
        await db.commit()
    return ok(data)


@router.get("/tools")
async def list_tools(user: CurrentUser = Depends(gateway_identity)) -> dict[str, Any]:
    """工具清单（对端据此对齐可调用范围；只出规格，不含 handler 与任何凭据）。"""
    _ = user
    return ok(registry.list_tools(), "获取成功")