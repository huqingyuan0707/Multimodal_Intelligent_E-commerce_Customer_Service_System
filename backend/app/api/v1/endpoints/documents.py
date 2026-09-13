"""知识库端点（真实落库，对齐 API 规范 §4.4）

链路：FormData 上传 → document_service（SHA256 租户内去重）→ ok()；重建索引落 tasks 行。
上传/重建/删除为敏感写操作，叠加 require_perm("kb") 做 Scope 校验；列表登录即放行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.rbac import get_current_user, require_perm
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import document_service, task_service

router = APIRouter(prefix="/documents", tags=["documents"])


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
) -> dict[str, Any]:
    """文档列表（真实空数据 [] 不报错；page/size 默认 20）。"""
    items = await document_service.list_docs(db, tenant=user.tenant, page=page, size=size)
    return ok(items, "获取成功")


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
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """重建索引（落 tasks 异步行，返回 task_id 轮询）。"""
    row = await task_service.create_task(
        db, tenant=user.tenant, username=user.username, type="kb.reindex", payload={}
    )
    return ok({"task_id": row.id}, "重建索引任务已提交")
