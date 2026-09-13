"""多媒体对象存储（本地盘，对齐数据模型 §5 + FR-1.2/1.3）

链路：endpoints/multimodal → save_upload → {file_id, url, path, sha256}
      → GET /multimodal/media/{file_id} 按租户回读。
布局：{MEDIA_DIR}/{tenant}/%Y/%m/{session_id}/{file_id}{ext}，
      与 S3 路径 `s3://app/{tenant}/%Y/%m/{session_id}/{uuid}.jpg|mp3` 同构，
      生产换 S3/MinIO 只换本模块实现，业务不感知。
红线：file_id 即 sha256 前 16 位 + 序号后缀，不可遍历；回读强制租户前缀，
      跨租户同 404；阻塞磁盘 IO 由调用方走 to_thread。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from app.config import settings

# ---------------- 落盘 ----------------


def _root() -> Path:
    """存储根（Settings 可调，测试可 monkeypatch）。"""
    return Path(settings.MEDIA_DIR)


def _safe_tenant(tenant: str) -> str:
    """租户目录名清洗：只留字母数字/中划/下划线，防路径穿越。"""
    cleaned = "".join(c for c in (tenant or "").strip() if c.isalnum() or c in ("-", "_"))
    return cleaned or "unknown-tenant"


def save_upload(
    *,
    tenant: str,
    kind: str,
    session_id: str,
    filename: str,
    raw: bytes,
) -> dict[str, str]:
    """落盘并返回 {file_id, url, path, sha256}（纯同步，调用方 to_thread）。

    kind：image | audio；ext 取原文件名后缀白名单外一律 .bin。
    file_id：sha256[:16]，同内容同租户同会话复用即覆盖写（幂等）。
    """
    digest = hashlib.sha256(raw).hexdigest()
    file_id = digest[:16]
    ext = (Path(filename or "").suffix or "").lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a", ".opus", ".webm"}
    if ext not in allowed:
        ext = ".bin"
    now = datetime.now()
    rel = Path(_safe_tenant(tenant)) / f"{now:%Y}" / f"{now:%m}" / (session_id or "nosession")
    target = _root() / rel / f"{file_id}{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    _ = uuid.uuid4().hex  # 占位：S3 版在此换 put_object，签名保持不变
    return {
        "file_id": file_id,
        "url": f"/api/v1/multimodal/media/{file_id}",
        "path": str(target),
        "sha256": digest,
    }


def resolve_path(*, tenant: str, file_id: str) -> Path | None:
    """按租户回查文件（防穿越：只在租户目录下 glob 同名）。"""
    cleaned = (file_id or "").strip()
    if not cleaned or len(cleaned) > 64 or any(c in cleaned for c in ("/", "\\", ".")):
        return None
    base = _root() / _safe_tenant(tenant)
    if not base.is_dir():
        return None
    hits = sorted(base.rglob(f"{cleaned}.*"))
    return hits[0] if hits else None
