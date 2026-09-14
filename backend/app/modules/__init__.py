"""业务内核包（Runtime / 编排等"专"能力，对齐后端工程化「API 薄 / Service 厚 / Runtime 专」）

链路：api/v1/endpoints → services（纯业务读写）∪ modules（状态机/注册中心/策略/执行器）。
口径：modules 只经 services 读写业务数据，不直接拼 SQL 落业务表；
      modules 之间按「契约 → 注册 → 策略 → 执行 → 编排」单向依赖，禁止反向 import。
"""

from __future__ import annotations

__all__: list[str] = []
