"""Agent Studio 服务（Prompt 版本灰度回滚 + 评测一键跑，对齐 FRD FR-3/页面设计 §3.6）

链路：endpoints/studio 薄封装 → 本模块纯业务（不依赖 FastAPI 对象）
     → prompt_versions / eval_runs 表；评测采样与判定口径复用
     scripts/eval_golden（阈值/TSV 解析同一出处，防双口径漂移）。
红线：一切查询带 tenant（租户隔离）；发布全量（gray=100）必须本租户最近
     eval accept_ok，否则 1001；variables 自动提取 {{var}}；灰度 0..100；
     回滚只认 version 名，原线上转 archived；评测跑在 BackgroundTasks，
     自建会话（请求会话已关闭），任何异常只记可观测不外抛。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.base import _now
from app.db.models import PromptVersion
from app.services import rag_governance
from app.services.studio_eval import (
    create_eval_run,
    eval_to_dict,
    get_eval_run,
    latest_accept_ok,
    list_eval_runs,
    run_eval,
    summarize_eval,
)

# ---------------- Prompt 版本口径 ----------------

PROMPT_STATUSES = ("draft", "gray", "online", "archived")

PROMPT_LABELS = {
    "draft": "草稿",
    "gray": "灰度中",
    "online": "线上",
    "archived": "已归档",
}

DESC_MAX_LEN = 200
CONTENT_MAX_LEN = 20000
GRAY_MIN = 0
GRAY_MAX = 100

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_VERSION_RE = re.compile(r"^v(\d+)$")


def extract_variables(content: str) -> list[str]:
    """提取 {{var}} 变量名（去重保序；发布/渲染共用同一口径）。"""
    seen: dict[str, None] = {}
    for name in _VAR_RE.findall(content or ""):
        seen.setdefault(name)
    return list(seen)


def prompt_to_dict(row: PromptVersion) -> dict[str, Any]:
    """版本行出参（含中文状态签 + 变量清单，前端直接渲染）。"""
    try:
        variables = json.loads(row.variables or "[]")
        variables = variables if isinstance(variables, list) else []
    except ValueError:
        variables = []
    return {
        "id": row.id,
        "version": row.version,
        "desc": row.desc or "",
        "content": row.content or "",
        "variables": variables,
        "gray": int(row.gray or 0),
        "status": row.status or "draft",
        "status_label": PROMPT_LABELS.get(row.status or "draft", "草稿"),
        "created_by": row.created_by or "",
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds")
        if row.created_at
        else "",
        "updated_at": row.updated_at.isoformat(sep=" ", timespec="seconds")
        if row.updated_at
        else "",
    }


async def _version_row(db: AsyncSession, *, tenant: str, version: str) -> PromptVersion:
    row = (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.tenant == tenant, PromptVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, f"Prompt 版本不存在：{version}", 404)
    return row


async def _next_version(db: AsyncSession, *, tenant: str) -> str:
    """下个版本号：本租户 v<N> 最大后缀 +1（非 vN 命名不参与编号）。"""
    versions = (
        (await db.execute(select(PromptVersion.version).where(PromptVersion.tenant == tenant)))
        .scalars()
        .all()
    )
    top = 0
    for name in versions:
        match = _VERSION_RE.match(str(name or ""))
        if match:
            top = max(top, int(match.group(1)))
    return f"v{top + 1}"


async def create_prompt(
    db: AsyncSession, *, tenant: str, desc: str, content: str, by: str
) -> dict[str, Any]:
    """新建草稿版本（版本号自动递增；正文空/超长 1001）。"""
    body = (content or "").strip()
    if not body:
        raise BusinessError(ErrorCode.PARAM_INVALID, "Prompt 正文不能为空", 400)
    if len(body) > CONTENT_MAX_LEN:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"Prompt 正文超长（上限 {CONTENT_MAX_LEN} 字）", 400
        )
    label = (desc or "").strip()[:DESC_MAX_LEN]
    row = PromptVersion(
        tenant=tenant,
        version=await _next_version(db, tenant=tenant),
        desc=label,
        content=body,
        variables=json.dumps(extract_variables(body), ensure_ascii=False),
        gray=0,
        status="draft",
        created_by=by,
    )
    db.add(row)
    await db.commit()
    return prompt_to_dict(row)


async def list_prompts(
    db: AsyncSession, *, tenant: str, page: int = 1, size: int = 20
) -> dict[str, Any]:
    """版本列表（线上优先，其次更新时间倒序；分页对象与坐席队列同口径）。"""
    stmt = select(PromptVersion).where(PromptVersion.tenant == tenant)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (
        (
            await db.execute(
                stmt.order_by(PromptVersion.created_at.desc(), PromptVersion.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    items = [prompt_to_dict(row) for row in rows]
    items.sort(key=lambda item: 0 if item["status"] == "online" else 1)
    return {"items": items, "total": total, "page": page, "size": size}


async def get_online(db: AsyncSession, *, tenant: str) -> dict[str, Any] | None:
    """当前线上版本（无则 None；对话链用 get_online_system 取正文）。"""
    row = (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.tenant == tenant, PromptVersion.status == "online"
            )
        )
    ).scalar_one_or_none()
    return prompt_to_dict(row) if row is not None else None


async def get_online_system(db: AsyncSession, *, tenant: str) -> str:
    """线上 system prompt 正文（无线上版本/正文空即 ""，调用方回退代码常量）。

    对话链每轮调一次（单行主键查询）；任何异常由调用方吞掉走回退，绝不拖垮对话。
    """
    try:
        online = await get_online(db, tenant=tenant)
    except Exception:
        return ""
    if not online:
        return ""
    return str(online.get("content") or "").strip()


async def _archive_live(db: AsyncSession, *, tenant: str) -> None:
    """发布/回滚前：本租户现存 online/gray 全部转 archived（单线上口径）。"""
    rows = (
        (
            await db.execute(
                select(PromptVersion).where(
                    PromptVersion.tenant == tenant,
                    PromptVersion.status.in_(("online", "gray")),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "archived"
        row.gray = 0
        row.updated_at = _now()


async def publish_prompt(
    db: AsyncSession, *, tenant: str, version: str, gray: int, by: str
) -> dict[str, Any]:
    """发布版本：gray=100 上线全量（需最近 eval accept_ok），否则进灰度。

    全量发布是生产动作：最近一次 done 评测 accept_ok=false（或一次都没跑过）
    即 1001 拒掉，前端红条与此同源；灰度发布不拦评测。
    """
    if gray < GRAY_MIN or gray > GRAY_MAX:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"灰度比例须在 {GRAY_MIN}..{GRAY_MAX} 之间", 400
        )
    row = await _version_row(db, tenant=tenant, version=version)
    if row.status == "archived":
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"{version} 已归档，不可直接发布（请新建版本）", 400
        )
    if gray >= 100 and not await latest_accept_ok(db, tenant=tenant):
        raise BusinessError(
            ErrorCode.PARAM_INVALID, "评测不达标，禁止发布全量（先跑评测并达验收线）", 400
        )
    await _archive_live(db, tenant=tenant)
    row.status = "online" if gray >= 100 else "gray"
    row.gray = 100 if gray >= 100 else gray
    row.updated_at = _now()
    await db.commit()
    await rag_governance.audit_write(
        db,
        tenant=tenant,
        actor=by,
        action="studio.prompt.publish",
        target=version,
        detail={"gray": int(row.gray), "status": row.status},
    )
    return prompt_to_dict(row)


async def set_gray(
    db: AsyncSession, *, tenant: str, version: str, gray: int, by: str
) -> dict[str, Any]:
    """调整灰度中版本的放量比例（仅 gray 态可调；online 改比例请发新版）。"""
    if gray < GRAY_MIN or gray > GRAY_MAX:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"灰度比例须在 {GRAY_MIN}..{GRAY_MAX} 之间", 400
        )
    row = await _version_row(db, tenant=tenant, version=version)
    if row.status != "gray":
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅灰度中的版本可调比例", 400)
    row.gray = gray
    row.updated_at = _now()
    await db.commit()
    await rag_governance.audit_write(
        db,
        tenant=tenant,
        actor=by,
        action="studio.prompt.gray",
        target=version,
        detail={"gray": gray},
    )
    return prompt_to_dict(row)


async def rollback_prompt(
    db: AsyncSession, *, tenant: str, version: str, by: str
) -> dict[str, Any]:
    """回滚：指定版本重上 online（gray=100），现存线上/灰度转 archived。

    二次确认由前端弹框承担；已是线上的版本重复回滚幂等（直接返回）。
    """
    row = await _version_row(db, tenant=tenant, version=version)
    if row.status == "online":
        return prompt_to_dict(row)
    await _archive_live(db, tenant=tenant)
    row.status = "online"
    row.gray = 100
    row.updated_at = _now()
    await db.commit()
    await rag_governance.audit_write(
        db, tenant=tenant, actor=by, action="studio.prompt.rollback", target=version, detail={}
    )
    return prompt_to_dict(row)


# 薄转发：评测 runs 已下沉 studio_eval，端点/后台旧导入口径不变。
__all__ = [
    "create_eval_run",
    "create_prompt",
    "eval_to_dict",
    "extract_variables",
    "get_eval_run",
    "get_online",
    "get_online_system",
    "latest_accept_ok",
    "list_eval_runs",
    "list_prompts",
    "prompt_to_dict",
    "publish_prompt",
    "rollback_prompt",
    "run_eval",
    "set_gray",
    "summarize_eval",
]
