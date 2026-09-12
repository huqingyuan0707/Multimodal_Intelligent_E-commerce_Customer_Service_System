"""FastAPI 入口（接入与编排层，对齐后端工程化启动节）

链路：中间件 → v1 router（/api/v1）→ /health|/ready 探针。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.core.middleware import TraceMiddleware
from app.db.session import init_models


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动建表（幂等，防空库 500；种子用户走 scripts/init_db.py）。"""
    await init_models()
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


@app.get("/health")
async def health() -> dict[str, str]:
    """存活探针。"""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """就绪探针（依赖检查后续补）。"""
    return {"status": "ready"}
