"""Agent Studio 端点（Prompt 版本灰度回滚 + 评测一键跑，对齐 API 规范 §4.13 + 页面设计 §3.6）

链路：StudioView 三窗格 → 本模块薄封装（解析→调 studio_service→ok()）
     → prompt_versions / eval_runs 表；工具试调复用 /agent/tools 已有端点。
权限：读（列表/线上/评测读）ops+admin；写（新建 ops+admin，发布/调灰/回滚 admin；
     评测一键跑 ops+admin）。可见范围一律 Token 推导，绝不信任请求体 tenant。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import studio_service

router = APIRouter(prefix="/studio", tags=["studio"])

OPS = require_any_perm("ops", "admin")
ADMIN = require_any_perm("admin")


class CreatePromptRequest(BaseModel):
    """新建 Prompt 版本入参（正文必填 2 万字内；说明 200 字内；版本号自动递增）."""

    desc: str = ""
    content: str = ""


class PublishPromptRequest(BaseModel):
    """发布入参（gray 0..100；100=全量上线，需最近评测达验收线）。"""

    gray: int = 100


class GrayPromptRequest(BaseModel):
    """灰度比例调整入参（仅灰度中版本可调，0..100）。"""

    gray: int = 50


class CreateEvalRequest(BaseModel):
    """评测一键跑入参（limit 采样数 1..200，默认 50；黄金集固定 default-200）。"""

    name: str = "default-200"
    limit: int = 50


@router.get("/prompts")
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Prompt 版本列表（线上置顶，其次更新倒序；服务端分页默认 20）。"""
    return ok(
        await studio_service.list_prompts(db, tenant=user.tenant, page=page, size=size), "获取成功"
    )


@router.post("/prompts")
async def create_prompt(
    payload: CreatePromptRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
) -> dict[str, Any]:
    """新建草稿版本（版本号 vN 自动递增；正文空/超长 1001）。"""
    return ok(
        await studio_service.create_prompt(
            db, tenant=user.tenant, desc=payload.desc, content=payload.content, by=user.username
        ),
        "草稿版本已创建",
    )


@router.get("/prompts/online")
async def get_online_prompt(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
) -> dict[str, Any]:
    """当前线上版本（无则 data=null；对话链 system prompt 取数口径同源）。"""
    return ok(await studio_service.get_online(db, tenant=user.tenant), "获取成功")


@router.post("/prompts/{version}/publish")
async def publish_prompt(
    version: str,
    payload: PublishPromptRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(ADMIN),
) -> dict[str, Any]:
    """发布版本（gray=100 全量需最近评测达验收线，否则 1001；其余进灰度）。

    发布即把本租户其他 online/gray 转 archived（单线上口径），动作记审计。
    """
    data = await studio_service.publish_prompt(
        db, tenant=user.tenant, version=version, gray=payload.gray, by=user.username
    )
    return ok(
        data, "已全量上线" if data["status"] == "online" else f"已进入灰度（{data['gray']}%）"
    )


@router.post("/prompts/{version}/gray")
async def set_prompt_gray(
    version: str,
    payload: GrayPromptRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(ADMIN),
) -> dict[str, Any]:
    """调整灰度中版本的放量比例（仅 gray 态可调；online 改比例请发新版）。"""
    return ok(
        await studio_service.set_gray(
            db, tenant=user.tenant, version=version, gray=payload.gray, by=user.username
        ),
        "灰度比例已更新",
    )


@router.post("/prompts/{version}/rollback")
async def rollback_prompt(
    version: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(ADMIN),
) -> dict[str, Any]:
    """回滚（指定版本重上 online，原线上转 archived；二次确认由前端承担）。"""
    return ok(
        await studio_service.rollback_prompt(
            db, tenant=user.tenant, version=version, by=user.username
        ),
        "已回滚到该版本",
    )


@router.post("/evals")
async def create_eval_run(
    payload: CreateEvalRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
) -> dict[str, Any]:
    """评测一键跑（建 run 即返 run_id；后台采样执行，轮询看 pending→done）。

    采样跑在本租户真实知识库上（默认 50 条，上限 200）；判定口径与
    scripts/eval_golden 同源（守卫→检索两道闸），结果落 eval_runs。
    """
    data = await studio_service.create_eval_run(
        db, tenant=user.tenant, name=payload.name, limit=payload.limit, by=user.username
    )
    background.add_task(
        studio_service.run_eval, tenant=user.tenant, run_id=data["id"], by=user.username
    )
    return ok(data, "评测任务已提交")


@router.get("/evals")
async def list_eval_runs(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """评测历史（创建时间倒序；服务端分页默认 20）。"""
    return ok(
        await studio_service.list_eval_runs(db, tenant=user.tenant, page=page, size=size),
        "获取成功",
    )


@router.get("/evals/{run_id}")
async def get_eval_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(OPS),
) -> dict[str, Any]:
    """评测 run 详情（含 score/pass/misses；跨租户 404）。"""
    return ok(await studio_service.get_eval_run(db, tenant=user.tenant, run_id=run_id), "获取成功")
