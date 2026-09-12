"""关键词 RAG 检索（P0 无向量权重的可运行链路，对齐 RAG 规范 §2/§3）

链路：Query → seed 知识双写口径 → bigram 重叠打分 → 租户/密级过滤 → TopK → 阈值拒答。
向量 + rerank 接入后替换 _score 即可，接口不变。
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import TypedDict

from app.config import settings

_DOCS: list[dict[str, object]] | None = None
_DOCS_LOCK = threading.Lock()


def _seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "seed" / "knowledge.json"


def _load_docs_sync() -> list[dict[str, object]]:
    """同步读种子文件（调用方必须走 to_thread，禁止在 async 直接调））。"""
    global _DOCS
    if _DOCS is None:
        with _DOCS_LOCK:
            if _DOCS is None:
                raw = json.loads(_seed_path().read_text(encoding="utf-8"))
                _DOCS = raw if isinstance(raw, list) else []
    return list(_DOCS or [])


def _bigrams(text: str) -> set[str]:
    chars = [c for c in text.strip() if not c.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def score(query: str, doc_text: str) -> float:
    """bigram 重叠率 0-1，纯函数可单测。"""
    q, d = _bigrams(query), _bigrams(doc_text)
    if not q:
        return 0.0
    return len(q & d) / len(q)


class _Hit(TypedDict):
    """内部命中行（score 保持 float，出口转 dict[str, object]）。"""

    title: str
    content: str
    source: str
    score: float


async def retrieve(
    query: str,
    tenant: str,
    top_k: int | None = None,
    threshold: float = 0.12,
) -> list[dict[str, object]]:
    """关键词召回：租户隔离（种子 tenant 或 public）→ 打分 → TopK → 阈值过滤。"""
    docs = await asyncio.to_thread(_load_docs_sync)
    scored: list[_Hit] = []
    for doc in docs:
        doc_tenant = str(doc.get("tenant", ""))
        if doc_tenant not in (tenant, "public"):
            continue
        text = f"{doc.get('title', '')} {doc.get('content', '')}"
        s = score(query, text)
        if s >= threshold:
            scored.append(
                {
                    "title": str(doc.get("title", "")),
                    "content": str(doc.get("content", "")),
                    "source": str(doc.get("id", "")),
                    "score": round(s, 4),
                }
            )
    scored.sort(key=lambda d: d["score"], reverse=True)
    top = scored[: top_k if top_k is not None else settings.TOP_K]
    return [dict(hit) for hit in top]
