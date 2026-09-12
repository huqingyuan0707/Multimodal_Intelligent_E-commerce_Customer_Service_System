"""知识库端点框架（上传/列表/重建索引，对齐 API 规范 §4.4）

链路：FormData 上传 → service（SHA256 去重）→ ok()；重建索引走 tasks 异步。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile

from app.core.exceptions import ErrorCode
from app.core.rbac import require_perm
from app.core.responses import fail, ok

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", dependencies=[Depends(require_perm("kb"))])
async def upload_document(file: UploadFile | None = None) -> object:
    """上传占位：空文件返回 PARAM_INVALID 中文可操作提示。"""
    if file is None:
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    return ok({"doc_id": "", "filename": file.filename}, "上传框架已就绪")


@router.get("")
async def list_documents() -> dict[str, object]:
    """文档列表占位。"""
    return ok([], "知识库框架已就绪")


@router.post("/reindex")
async def reindex() -> dict[str, object]:
    """重建索引占位，返回 task_id 轮询。"""
    return ok({"task_id": ""}, "重建索引任务已提交")
