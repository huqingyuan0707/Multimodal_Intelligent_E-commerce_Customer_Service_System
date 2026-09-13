"""FastAPI 入口（接入与编排层，对齐后端工程化启动节 + API 规范 §2 错误码）

链路：中间件 → v1 router（/api/v1）→ /health|/ready 探针。
异常统一收口信封：BusinessError 按号段码；HTTP 401/403/404 转 1002/1003/1004；
参数校验转 1001；未知异常转 5000（不泄露堆栈，模型/外部失败走降级绝不 500）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.middleware import TraceMiddleware
from app.core.responses import fail
from app.db.seed import seed_on_startup
from app.db.session import init_models

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动建表（幂等，防空库 500）+ 种子账号（SEED_ON_START=false 可关，生产必关）。"""
    await init_models()
    if settings.SEED_ON_START:
        await seed_on_startup()
    yield


app = FastAPI(title="multimodal-cs", version="0.1.0", lifespan=lifespan)
app.add_middleware(TraceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(BusinessError)
async def business_error_handler(_: Request, exc: BusinessError) -> JSONResponse:
    """业务失败统一转 fail() 信封：services 抛 BusinessError，端点不写 try/except（分层红线）。"""
    return fail(exc.code, exc.msg, exc.http_status)


def _http_to_envelope(status: int, detail: object) -> JSONResponse:
    """HTTP 异常转信封：401→1002/403→1003/404→1004，其余→5000（前端按码分支）。"""
    text = str(detail) if detail else ""
    if status == 401:
        return fail(ErrorCode.UNAUTHORIZED, text or "未登录或登录已过期", 401)
    if status == 403:
        return fail(ErrorCode.FORBIDDEN, text or "权限不足", 403)
    if status == 404:
        return fail(ErrorCode.NOT_FOUND, text or "资源不存在", 404)
    return fail(ErrorCode.INTERNAL, "系统繁忙，请稍后重试", status if status < 500 else 500)


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI HTTPException（含 get_current_user 的 401/403）统一转信封。"""
    return _http_to_envelope(int(exc.status_code), exc.detail)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette 层 HTTP 异常（如无 token 的 401）统一转信封。"""
    return _http_to_envelope(int(exc.status_code), exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """参数校验失败转 1001（中文可操作，不暴露原始字段堆栈）。"""
    logger.warning("param invalid: %s", str(exc)[:300])
    return fail(ErrorCode.PARAM_INVALID, "请求参数有误，请检查后重试", 400)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """兜底：未知异常转 5000，日志留痕，前端只收中文提示（模型失败走降级不进这里）。"""
    logger.exception("unhandled error: %s", exc)
    return fail(ErrorCode.INTERNAL, "系统繁忙，请稍后重试", 500)


@app.get("/health")
async def health() -> dict[str, str]:
    """存活探针。"""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """就绪探针（依赖检查后续补）。"""
    return {"status": "ready"}
