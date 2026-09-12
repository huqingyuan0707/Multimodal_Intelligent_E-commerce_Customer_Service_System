"""业务服务层占位（纯函数，不依赖 FastAPI 对象，对齐 AGENTS.md §3）

链路：endpoints 解析鉴权 → 调此处编排 → 返回数据给 ok()。
具体业务后续按 FRDv2 落 service 文件。
"""

from __future__ import annotations
