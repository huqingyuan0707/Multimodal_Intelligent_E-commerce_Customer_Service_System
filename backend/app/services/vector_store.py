"""向量存储适配层（上传第 4 步向量化，对齐 RAG 规范 §1/数据模型 §3）

链路：document 切分 → embed_chunks（to_thread）→ upsert（vector_id 回写 kb_chunks）
      → retrieve 时 search 取向量分 → 删除时 delete_by_chunk。
红线：业务不直连 Chroma/pgvector；向量键 `{tenant}:{chunk_id}` 强制租户隔离；
      模型下载前 setdefault HF_ENDPOINT；惰性单例双检锁；status() 供治理巡检。
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
from typing import Any

from app.config import settings

_DIM = settings.EMB_DIM
_meta_lock = threading.Lock()
_ready = False
_store: dict[str, list[float]] = {}


def _ensure_ready() -> None:
    """惰性就绪（双检锁；P0 无重模型，仅固定 HF 镜像变量保证后续 BGE 可下载）。"""
    global _ready
    if _ready:
        return
    with _meta_lock:
        if _ready:
            return
        os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
        _ready = True


def embed_text(text: str) -> list[float]:
    """确定性哈希向量（P0 stdlib：bigram 哈希到 EMB_DIM 维并 L2 归一，纯函数可单测）。

    BGE 接入后替换本函数体即可，签名与 vector_id 口径不变。
    """
    _ensure_ready()
    vec = [0.0] * settings.EMB_DIM
    chars = [c for c in (text or "") if not c.isspace()]
    grams = (
        {chars[i] + chars[i + 1] for i in range(len(chars) - 1)} if len(chars) >= 2 else set(chars)
    )
    for gram in grams:
        idx = int(hashlib.sha256(gram.encode("utf-8")).hexdigest(), 16) % settings.EMB_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _key(tenant: str, chunk_id: str) -> str:
    return f"{tenant}:{chunk_id}"


async def upsert(tenant: str, chunk_ids: list[str], texts: list[str]) -> list[str]:
    """写入向量（返回 vector_id 列表供 kb_chunks 回写；同租户覆盖写）。"""
    _ensure_ready()
    ids: list[str] = []
    for cid, text in zip(chunk_ids, texts, strict=False):
        vid = _key(tenant, cid)
        _store[vid] = embed_text(text)
        ids.append(vid)
    return ids


async def delete_by_chunk(tenant: str, chunk_ids: list[str]) -> int:
    """按块删向量（文档删除/reindex 前必调，保证向量与 chunks 同删）。"""
    removed = 0
    for cid in chunk_ids:
        if _store.pop(_key(tenant, cid), None) is not None:
            removed += 1
    return removed


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


async def search(
    tenant: str, query: str, chunk_ids: list[str], top_k: int | None = None
) -> dict[str, float]:
    """向量打分（仅返回本租户键的余弦分；缺向量记 0 不抛异常，自动回退关键词路）。"""
    _ensure_ready()
    qvec = embed_text(query)
    scores: dict[str, float] = {}
    for cid in chunk_ids:
        vec = _store.get(_key(tenant, cid))
        scores[cid] = _cosine(qvec, vec) if vec is not None else 0.0
    limit = top_k if top_k is not None else settings.TOP_K * 4
    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)[:limit]
    return {k: round(scores[k], 4) for k in ranked}


def status() -> dict[str, Any]:
    """可用性巡检（供 /governance/status；memory 后端恒可用，切 Chroma 后探活）。"""
    _ensure_ready()
    return {
        "backend": settings.VECTOR_BACKEND,
        "model": settings.EMB_MODEL,
        "dim": settings.EMB_DIM,
        "available": True,
        "vectors": len(_store),
    }
