"""Agent 内核（FRDv2 FR-3 状态机 / FR-5 工具注册中心，执行步骤 B）

链路：main.lifespan → bootstrap.startup() 注册连接器 → endpoints/agent 对外暴露
      → runtime.run() 编排（policy 鉴权 → executor 执行 → checkpoint 落 tasks）。
分层：contracts（契约）→ registry（注册）→ policy（策略）→ executor（执行）→ runtime（编排），
      单向依赖，禁止反向 import；本包不直连业务表，一律经 services。
"""

from __future__ import annotations

from app.modules.agent import connectors, contracts, executor, policy, registry, runtime
from app.modules.agent.bootstrap import startup

__all__ = [
    "connectors",
    "contracts",
    "executor",
    "policy",
    "registry",
    "runtime",
    "startup",
]
