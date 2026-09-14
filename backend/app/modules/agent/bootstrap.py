"""Agent 内核启动注册（main.py lifespan 调用，对齐 FRDv2 FR-5 工具注册中心 / 执行步骤 B）

链路：main.lifespan → startup() → connectors.register_all() → registry 装载 6 个连接器。
口径：注册幂等（重复启动只覆盖同规格项）；注册失败只告警不阻断启动——
      编排内核是增强能力，缺它服务仍要能起（对齐「绝不 500」红线）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.agent import connectors, registry

logger = logging.getLogger(__name__)


def register_builtin() -> list[str]:
    """装载内置连接器并做规格自检（问题只告警，保证可观测但不拦启动）。"""
    names = connectors.register_all()
    problems = connectors.self_check()
    if problems:
        logger.warning("agent tool spec self-check: %s", "；".join(problems))
    logger.info("agent tools registered: %s", ", ".join(names))
    return names


async def startup() -> dict[str, Any]:
    """FastAPI 启动钩子：返回注册结果供 /health 之外的排查使用。"""
    try:
        names = register_builtin()
    except Exception as exc:  # 启动期任何异常都不该让服务起不来（注册失败降级为空注册表）
        logger.warning("agent tool registration skipped: %s", exc)
        return {"registered": 0, "tools": [], "error": str(exc)[:200]}
    return {"registered": len(names), "tools": names, "count": registry.count()}
