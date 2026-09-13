"""知识库端点（真实落库，对齐 API 规范 §4.4）

链路：FormData 上传 → document_service（SHA256 租户内去重）→ ok()；重建索引落 tasks 行。
上传/重建/删除为敏感写操作，叠加 require_perm("kb") 做 Scope 校验；列表登录即放行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.rbac import get_current_user, require_perm
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import document_service, task_service

router = APIRouter(prefix="/documents", tags=["documents"])


class DocUpdateRequest(BaseModel):
    """编辑文档入参（端点私有 DTO；内容变则版本 +1，撞他篇 1001）。"""

    title: str
    content: str = ""
    security_level: str = "internal"
    channels: list[str] = ["all"]
    valid_from: str = ""
    valid_to: str = ""


@router.post("/upload", dependencies=[Depends(require_perm("kb"))])
async def upload_document(
    file: UploadFile | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """上传入库：空文件 1001；重复 SHA256 返回已跳过（中文可操作提示）。"""
    if file is None or not (file.filename or "").strip():
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    raw = await file.read()
    if not raw:
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    try:
        text = raw[:20000].decode("utf-8", errors="ignore")
    except ValueError:
        text = ""
    row, skipped = await document_service.get_or_create_doc(
        db, tenant=user.tenant, title=file.filename or "未命名文档", content=text, raw=raw
    )
    if skipped:
        return ok(
            {"doc_id": row.id, "sha256": row.sha256, "skipped": True},
            "内容与当前版本一致（SHA256 相同），已跳过重复入库",
        )
    return ok({"doc_id": row.id, "sha256": row.sha256, "skipped": False}, "文档已入库")


@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    """文档列表（分页对象；page/size 默认 20；标题模糊筛选；空数据 items=[] 不报错）。"""
    items = await document_service.list_docs(
        db, tenant=user.tenant, page=page, size=size, keyword=keyword
    )
    total = await document_service.count_docs(db, tenant=user.tenant, keyword=keyword)
    return ok({"items": items, "total": total, "page": page, "size": size}, "获取成功")


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """文档详情（含正文与元数据，供预览/编辑回显）。"""
    row = await document_service.get_doc(db, tenant=user.tenant, doc_id=doc_id)
    return ok(document_service.detail_to_dict(row), "获取成功")


@router.put("/{doc_id}", dependencies=[Depends(require_perm("kb"))])
async def update_document(
    doc_id: str,
    payload: DocUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """编辑文档（内容变则版本 +1；撞已有内容 1001 中文提示）。"""
    row = await document_service.update_doc(
        db,
        tenant=user.tenant,
        doc_id=doc_id,
        title=payload.title,
        content=payload.content,
        security_level=payload.security_level,
        channels=payload.channels,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    return ok(document_service.detail_to_dict(row), "文档已更新")


@router.delete("/{doc_id}", dependencies=[Depends(require_perm("kb"))])
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """删除文档（破坏性操作，前端先 confirm）。"""
    await document_service.delete_doc(db, tenant=user.tenant, doc_id=doc_id)
    return ok({"id": doc_id}, "文档已删除")


@router.post("/reindex", dependencies=[Depends(require_perm("kb"))])
async def reindex(
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """重建索引（落 tasks 行 + 后台真实执行分块重建，GET /tasks/{id} 轮询进度）。"""
    row = await task_service.create_task(
        db, tenant=user.tenant, username=user.username, type="kb.reindex", payload={}
    )
    background.add_task(document_service.run_reindex, tenant=user.tenant, task_id=row.id)
    return ok({"task_id": row.id}, "重建索引任务已提交")
