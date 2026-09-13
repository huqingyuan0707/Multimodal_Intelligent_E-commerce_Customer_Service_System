"""SSE 流式传输件（事件幂等 + 分片 + 回放解析，对齐 API 规范 §5）

链路：endpoints/chat → stream_id_for（幂等键派生事件 id）→ chunk_text（增量分片）
      → done；重放时 _loads_* 解析落库行，回相同事件 id，前端天然去重。
本模块只做传输编排，问答编排仍在 chat_service（answer/run_text_turn）。
"""

from __future__ import annotations

import hashlib
import json
import uuid

from app.config import settings


def stream_id_for(client_msg_id: str | None) -> str:
    """SSE 事件 id 前缀：由幂等键确定性派生，重放产出相同 id，前端天然去重。

    无键（旧客户端）则随机，本轮内去重、跨轮不保证。
    """
    key = (client_msg_id or "").strip()
    if not key:
        return uuid.uuid4().hex[:8]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def chunk_text(text: str, size: int | None = None) -> list[str]:
    """message 事件分片（增量渲染粒度，长度走 Settings.SSE_CHUNK_CHARS）。"""
    width = size if size and size > 0 else settings.SSE_CHUNK_CHARS
    if width <= 0:
        width = 120
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def loads_list(raw: str) -> list[dict[str, object]]:
    """回放解析：citations/attachments JSON 文本 → 列表，坏数据兜底空列表不断流。"""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return []
    return [dict(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def loads_dict(raw: str) -> dict[str, object]:
    """回放解析：guard JSON 文本 → 字典，坏数据兜底通过不断流。"""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return {"pass": True}
    return dict(data) if isinstance(data, dict) else {"pass": True}
