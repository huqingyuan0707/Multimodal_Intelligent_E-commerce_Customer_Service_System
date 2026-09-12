"""中间件与可观测占位（trace 注入 + 耗时记录，对齐部署工程化可观测）

链路：请求 → trace_id → observability.record() → 日志/指标。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TraceMiddleware(BaseHTTPMiddleware):
    """注入 X-Trace-Id，框架侧给 fail() 补 trace_id。"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Trace-Id", uuid.uuid4().hex[:16])
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Elapsed-Ms"] = str(int((time.perf_counter() - started) * 1000))
        return response


def register_middlewares(app: object) -> None:
    """占位：具体 app.add_middleware 调用在 main.py 补。"""
    _ = app
    return None
