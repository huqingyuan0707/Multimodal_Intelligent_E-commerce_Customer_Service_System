"""知识库文档服务（前置地基：真实落库，对齐 API 规范 §4.4 + 数据模型文档 §2）

链路：endpoints/documents 薄封装 → 本模块 → kb_docs 表（sha256 租户内去重）。
红线：所有查询强制按 tenant 过滤；上传去重返回 skipped=True（中文提示由端点组装）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import KbChunk, KbDoc

# 密级三档（RAG 规范 §3：confidential 需 kb 权限；会话侧默认只召回 public）
LEVELS = ("public", "internal", "confidential")


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_date(text: str, field: str) -> datetime | None:
    """生效期解析：空=不限；支持 YYYY-MM-DD 与 YYYY-MM-DD HH:mm:ss，非法 1001。"""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise BusinessError(ErrorCode.PARAM_INVALID, f"{field}格式不正确（YYYY-MM-DD）")


def _parse_channels(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v for v in value if v.strip()] or ["all"]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()] or ["all"]
    return ["all"]


def _channels_of(row: KbDoc) -> list[str]:
    try:
        loaded = json.loads(row.channels or "")
    except ValueError:
        return ["all"]
    return _parse_channels(loaded)


def doc_to_dict(row: KbDoc) -> dict[str, Any]:
    return {
        "id": row.id,
        "doc_id": row.id,
        "title": row.title,
        "security_level": row.security_level,
        "channels": _channels_of(row),
        "valid_from": _dt_text(row.valid_from),
        "valid_to": _dt_text(row.valid_to),
        "sha256": row.sha256,
        "version": row.version,
        "created_at": _dt_text(row.created_at),
    }


def detail_to_dict(row: KbDoc) -> dict[str, Any]:
    """详情（含正文，供预览/编辑；列表保持轻量不带 content）。"""
    data = doc_to_dict(row)
    data["content"] = row.content
    return data


def parse_seed_markdown(text: str) -> dict[str, Any]:
    """解析种子 Markdown：front-matter 七字段 + 正文（去 HTML 注释行）。

    无 front-matter 时全篇当正文、标题取首个 # 行；字段缺失走模型默认值。
    """
    meta: dict[str, str] = {}
    body = text or ""
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            for line in body[3:end].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            body = body[end + 4 :]
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("<!--")]
    title = meta.get("title", "")
    if not title:
        for ln in lines:
            if ln.startswith("# "):
                title = ln[2:].strip()
                break
    return {
        "title": title,
        "security_level": meta.get("security_level", "internal"),
        "channels": _parse_channels(meta.get("channels", "[all]").strip("[]")),
        "valid_from": _parse_date(meta.get("valid_from", ""), "生效起"),
        "valid_to": _parse_date(meta.get("valid_to", ""), "生效止"),
        "version": int(meta["version"]) if meta.get("version", "1").isdigit() else 1,
        "body": "\n".join(lines).strip() + "\n",
    }


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_chunks(content: str) -> list[str]:
    """按业务主题切分：`##` 起新块（标题行并入首块）；超长块按段落硬切到 KB_CHUNK_CHARS。

    纯函数可单测；BGE 语义切分接入后替换本函数即可，调用方不变。
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in (content or "").splitlines():
        has_body = any(not part.startswith("#") and part.strip() for part in current)
        if line.startswith("##") and has_body:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    cap = settings.KB_CHUNK_CHARS
    out: list[str] = []
    for block in blocks:
        text = block.strip("\n")
        if not text.strip():
            continue
        if len(text) <= cap:
            out.append(text)
            continue
        buf = ""
        for para in text.split("\n"):
            if buf.strip() and len(buf) + len(para) + 1 > cap:
                out.append(buf.strip())
                buf = ""
            buf += para + "\n"
        if buf.strip():
            out.append(buf.strip())
    stripped = (content or "").strip()
    return out or ([stripped] if stripped else [])


async def _write_chunks(db: AsyncSession, doc_id: str, chunks: list[str]) -> int:
    """落 kb_chunks 行（ord 即块序，供引用 source 定位与多样性裁剪）。"""
    db.add_all([KbChunk(doc_id=doc_id, ord=i, content=part) for i, part in enumerate(chunks)])
    await db.flush()
    return len(chunks)


async def rebuild_chunks(db: AsyncSession, *, tenant: str) -> dict[str, int]:
    """重建租户全部分块（reindex 执行体）：删旧块 → 按正文重切 → 单事务提交。"""
    docs = list((await db.execute(select(KbDoc).where(KbDoc.tenant == tenant))).scalars())
    total_chunks = 0
    for doc in docs:
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == doc.id))
        total_chunks += await _write_chunks(db, doc.id, split_chunks(doc.content))
    await db.commit()
    return {"docs": len(docs), "chunks": total_chunks}


async def run_reindex(*, tenant: str, task_id: str) -> None:
    """reindex 后台执行：自建会话（请求会话此时已关闭）→ 重建分块 → task 进度落库。

    异常只记 task error，绝不抛（后台抛异常只会烂在日志里，前端靠轮询感知）。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_engine
    from app.services import task_service

    maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with maker() as db:
            await task_service.mark_task(db, tenant=tenant, task_id=task_id, status="running")
            stats = await rebuild_chunks(db, tenant=tenant)
            await task_service.mark_task(
                db, tenant=tenant, task_id=task_id, status="done", progress=1.0, output=stats
            )
    except Exception as exc:
        with contextlib.suppress(Exception):
            async with maker() as db:
                await task_service.mark_task(
                    db, tenant=tenant, task_id=task_id, status="error", error=str(exc)[:500]
                )


async def list_docs(
    db: AsyncSession, *, tenant: str, page: int = 1, size: int = 20, keyword: str = ""
) -> list[dict[str, Any]]:
    """文档列表（租户隔离倒序；标题模糊筛选；page/size 默认 20；端点包成分页对象）。"""
    stmt = select(KbDoc).where(KbDoc.tenant == tenant)
    if keyword.strip():
        stmt = stmt.where(KbDoc.title.like(f"%{keyword.strip()}%"))
    stmt = stmt.order_by(KbDoc.created_at.desc()).offset((page - 1) * size).limit(size)
    rows = list((await db.execute(stmt)).scalars())
    return [doc_to_dict(r) for r in rows]


async def count_docs(db: AsyncSession, *, tenant: str, keyword: str = "") -> int:
    stmt = select(func.count()).select_from(KbDoc).where(KbDoc.tenant == tenant)
    if keyword.strip():
        stmt = stmt.where(KbDoc.title.like(f"%{keyword.strip()}%"))
    total = (await db.execute(stmt)).scalar_one()
    return int(total)


async def get_or_create_doc(
    db: AsyncSession, *, tenant: str, title: str, content: str, raw: bytes
) -> tuple[KbDoc, bool]:
    """按 sha256 去重入库：已存在返回 (旧行, True)，新建返回 (新行, False)。"""
    digest = sha256_of(raw)
    existed = (
        await db.execute(select(KbDoc).where(KbDoc.tenant == tenant, KbDoc.sha256 == digest))
    ).scalar_one_or_none()
    if existed is not None:
        return existed, True
    if not (title or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请至少选择一个文件")
    row = KbDoc(
        tenant=tenant,
        title=title.strip()[:200],
        content=content,
        sha256=digest,
        version=1,
    )
    db.add(row)
    await db.flush()
    await _write_chunks(db, row.id, split_chunks(content))
    await db.commit()
    return row, False


async def delete_doc(db: AsyncSession, *, tenant: str, doc_id: str) -> None:
    """删除文档（跨租户 404；分块级联由外键处理）。"""
    row = (
        await db.execute(select(KbDoc).where(KbDoc.id == doc_id, KbDoc.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "文档不存在或无权访问", 404)
    # SQLite 外键级联不可靠，显式删块（KbChunk.doc_id 无DB级联保障时防孤儿）
    await db.execute(delete(KbChunk).where(KbChunk.doc_id == doc_id))
    await db.delete(row)
    await db.commit()


async def get_doc(db: AsyncSession, *, tenant: str, doc_id: str) -> KbDoc:
    """取单篇（跨租户 404；预览/编辑前置）。"""
    row = (
        await db.execute(select(KbDoc).where(KbDoc.id == doc_id, KbDoc.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "文档不存在或无权访问", 404)
    return row


async def update_doc(
    db: AsyncSession,
    *,
    tenant: str,
    doc_id: str,
    title: str,
    content: str,
    security_level: str,
    channels: list[str] | None,
    valid_from: str = "",
    valid_to: str = "",
) -> KbDoc:
    """编辑文档：内容变则重算 sha（撞他篇 1001）+ 版本 +1；元数据直接覆盖。"""
    if not (title or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "标题不能为空")
    if security_level not in LEVELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, "密级仅支持 public/internal/confidential")
    row = await get_doc(db, tenant=tenant, doc_id=doc_id)
    digest = sha256_of((content or "").encode("utf-8"))
    content_changed = digest != row.sha256
    if content_changed:
        clash = (
            await db.execute(
                select(KbDoc).where(
                    KbDoc.tenant == tenant, KbDoc.sha256 == digest, KbDoc.id != doc_id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise BusinessError(ErrorCode.PARAM_INVALID, "与其他文档内容重复，已跳过保存")
        row.sha256 = digest
        row.version += 1
    row.title = title.strip()[:200]
    row.content = content or ""
    if content_changed:
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == row.id))
        await _write_chunks(db, row.id, split_chunks(row.content))
    row.security_level = security_level
    row.channels = json.dumps(_parse_channels(channels or ["all"]), ensure_ascii=False)
    row.valid_from = _parse_date(valid_from, "生效起")
    row.valid_to = _parse_date(valid_to, "生效止")
    await db.commit()
    return row
