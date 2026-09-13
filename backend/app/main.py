"""FastAPI 入口（接入与编排层，对齐后端工程化启动节）

链路：中间件 → v1 router（/api/v1）→ /health|/ready 探针。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import BusinessError
from app.core.middleware import TraceMiddleware
from app.core.responses import fail
from app.db.seed import seed_on_startup
from app.db.session import init_models


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


@app.get("/health")
async def health() -> dict[str, str]:
    """存活探针。"""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """就绪探针（依赖检查后续补）。"""
    return {"status": "ready"}
