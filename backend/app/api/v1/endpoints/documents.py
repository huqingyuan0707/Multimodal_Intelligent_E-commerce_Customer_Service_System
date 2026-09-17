"""知识库端点（13 步上传侧 + P1 生命周期/版本/检索测试，对齐 API 规范 §4.4 + RAG 规范 §1/§5）

链路：FormData 上传 → ingest_upload（解析→切分→向量→audit）→ ok()；重建落 tasks。
上传/重建/删除/回滚/流转叠加 require_perm("kb")；列表/详情/版本/统计/检索测试登录即放行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, UploadFile
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
    topic: str = ""
    security_level: str = "internal"
    channels: list[str] = ["all"]
    valid_from: str = ""
    valid_to: str = ""


class RetrieveTestRequest(BaseModel):
    """检索测试入参（运营后台预览召回分数/过滤原因；top_k 1..20）。"""

    query: str
    top_k: int = 5
    channel: str = "all"


class RollbackRequest(BaseModel):
    """回滚入参（目标历史版本号；旧内容另起新版本）。"""

    version: int


class TransitionRequest(BaseModel):
    """生命周期流转入参（submit/publish/archive/reopen）。"""

    action: str


@router.post("/upload", dependencies=[Depends(require_perm("kb"))])
async def upload_document(
    file: UploadFile | None = None,
    security_level: str = Form(default="internal"),
    channels: str = Form(default="all"),
    valid_from: str = Form(default=""),
    valid_to: str = Form(default=""),
    topic: str = Form(default=""),
    status: str = Form(default="published"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """上传入库：解析→切分→向量→audit 全在 service；空文件 1001；重复 SHA256 已跳过。"""
    if file is None or not (file.filename or "").strip():
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    raw = await file.read()
    if not raw:
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    row, skipped = await document_service.ingest_upload(
        db,
        tenant=user.tenant,
        actor=user.username,
        filename=file.filename or "未命名文档",
        raw=raw,
        security_level=(security_level or "internal").strip(),
        channels=[c.strip() for c in (channels or "all").split(",") if c.strip()],
        valid_from=(valid_from or "").strip(),
        valid_to=(valid_to or "").strip(),
        topic=(topic or "").strip(),
        status=(status or "published").strip(),
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


@router.post("/retrieve-test")
async def retrieve_test(
    payload: RetrieveTestRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """检索测试（运营预览召回分数/过滤原因；密级按调用者角色可见集；top_k 越界 1001）。

    对齐 RAG 规范 §5 + FR-13.5：只读不写 DB，不断流。
    """
    from app.services import knowledge_service

    query = (payload.query or "").strip()
    if not query:
        return fail(ErrorCode.PARAM_INVALID, "请输入测试 query", 400)
    if payload.top_k < 1 or payload.top_k > 20:
        return fail(ErrorCode.PARAM_INVALID, "top_k 仅支持 1..20", 400)
    # 角色决定密级可见集（CurrentUser.roles 已是列表，与 retrieve 口径一致）
    roles = [str(r).strip() for r in (user.roles or []) if str(r).strip()]
    data = await knowledge_service.retrieve_debug(
        query,
        user.tenant,
        db,
        roles=roles,
        channel=(payload.channel or "all").strip() or "all",
        top_k=payload.top_k,
    )
    return ok(data, "获取成功")


@router.get("/stats")
async def document_stats(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """引用统计（FR-13.5）：按主题聚合引用命中 + 引用为 0 超 30 天提示复核/归档。"""
    return ok(await document_service.doc_stats(db, tenant=user.tenant), "获取成功")


@router.get("/{doc_id}/versions")
async def document_versions(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """版本历史倒序（回滚/版本抽屉数据源；跨租户 404）。"""
    items = await document_service.list_versions(db, tenant=user.tenant, doc_id=doc_id)
    return ok({"items": items, "total": len(items)}, "获取成功")


@router.post("/{doc_id}/rollback", dependencies=[Depends(require_perm("kb"))])
async def rollback_document(
    doc_id: str,
    payload: RollbackRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """回滚到历史版本（旧内容另起新版本，不覆盖旧版；目标不存在 404）。"""
    row = await document_service.rollback_doc(
        db, tenant=user.tenant, doc_id=doc_id, version=payload.version, actor=user.username
    )
    return ok(document_service.detail_to_dict(row), f"已回滚，当前版本 v{row.version}")


@router.post("/{doc_id}/transition", dependencies=[Depends(require_perm("kb"))])
async def transition_document(
    doc_id: str,
    payload: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """生命周期流转（submit/publish/archive/reopen；发布需换人复核，非法流转 1001）。"""
    row = await document_service.transition_doc(
        db,
        tenant=user.tenant,
        doc_id=doc_id,
        action=(payload.action or "").strip(),
        actor=user.username,
    )
    return ok(document_service.detail_to_dict(row), "状态已更新")


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
        topic=payload.topic,
        security_level=payload.security_level,
        channels=payload.channels,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        actor=user.username,
    )
    return ok(document_service.detail_to_dict(row), "文档已更新")


@router.delete("/{doc_id}", dependencies=[Depends(require_perm("kb"))])
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """删除文档（分块+向量级联删+审计；前端先 confirm）。"""
    await document_service.delete_doc(db, tenant=user.tenant, doc_id=doc_id, actor=user.username)
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
