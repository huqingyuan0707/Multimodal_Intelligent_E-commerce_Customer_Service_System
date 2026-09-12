"""v1 router 别名（兼容 main.py 的 from app.api.v1.router import api_router）

链路：main → api_router（定义见 __init__.py）。
"""

from __future__ import annotations

from app.api.v1 import api_router

__all__ = ["api_router"]
