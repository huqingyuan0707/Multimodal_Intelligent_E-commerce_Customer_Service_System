"""多媒体对象存储（本地盘 / S3·MinIO 双后端，对齐数据模型 §5 + FR-1.2/1.3）

链路：endpoints/multimodal → save_upload → {file_id, url, path, sha256}
      → GET /multimodal/media/{file_id} 按租户回读。
布局：`{tenant}/%Y/%m/{session_id}/{file_id}{ext}`——local 落 MEDIA_DIR，s3 落 S3_BUCKET，
      两侧同构（数据模型 §5 `s3://app/{tenant}/%Y/%m/{session_id}/{uuid}.jpg|mp3`）。
S3 口径：MEDIA_BACKEND=s3 时对象存储为源，本地盘退化为「回读物化缓存」：
      save_upload 先写对象、成功才落缓存；写失败显式报 5001/503（不回退本地盘，防两处副本分叉）；
      resolve_path 命中缓存即不下载，冷路径才回源。
红线：file_id 即 sha256 前 16 位，不可遍历；回读强制租户前缀，跨租户同 404；
      阻塞 IO（磁盘/boto3）由调用方走 to_thread。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode

_s3_holder: dict[str, Any] = {}  # 惰性客户端单例
_s3_off = False  # 客户端构造失败（缺 boto3 / 配置错）即 sticky 降级：s3 模式下上传将显式报 5001

# 后缀白名单（kind=image|audio 共用；白名单外一律 .bin）
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a", ".opus", ".webm"}


def _root() -> Path:
    """存储根（Settings 可调，测试可 monkeypatch）。"""
    return Path(settings.MEDIA_DIR)


def _safe_tenant(tenant: str) -> str:
    """租户目录名清洗：只留字母数字/中划/下划线，防路径穿越。"""
    cleaned = "".join(c for c in (tenant or "").strip() if c.isalnum() or c in ("-", "_"))
    return cleaned or "unknown-tenant"


def _use_s3() -> bool:
    """是否启用对象存储后端（local | s3，见 Settings.MEDIA_BACKEND）。"""
    return (settings.MEDIA_BACKEND or "local").strip().lower() == "s3"


def _s3_client() -> Any:
    """取 S3/MinIO 客户端（惰性单例；缺 boto3 或配置错即 sticky 降级，返回 None）。"""
    global _s3_off
    if _s3_off:
        return None
    if "c" not in _s3_holder:
        try:
            import boto3

            _s3_holder["c"] = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT or None,
                region_name=settings.S3_REGION or None,
                aws_access_key_id=settings.S3_ACCESS_KEY or None,
                aws_secret_access_key=settings.S3_SECRET_KEY.get_secret_value() or None,
            )
        except Exception:  # 缺依赖/配置错：可选后端，绝不打断上传
            _s3_off = True
            return None
    return _s3_holder["c"]


def status() -> dict[str, Any]:
    """治理巡检口径（/governance/status 第八层）：后端 + 客户端可用性 + 缓存根/桶名。"""
    use_s3 = _use_s3()
    return {
        "backend": "s3" if use_s3 else "local",
        "available": (not use_s3) or _s3_client() is not None,
        "degraded": use_s3 and _s3_off,
        "root": str(_root()),
        "bucket": settings.S3_BUCKET if use_s3 else "",
    }


def _rel_dir(tenant: str, session_id: str) -> Path:
    """对象相对目录：{tenant}/%Y/%m/{session_id}（本地与 S3 同构）。"""
    now = datetime.now()
    return Path(_safe_tenant(tenant)) / f"{now:%Y}" / f"{now:%m}" / (session_id or "nosession")


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
    s3 模式：对象存储为源（put_object 成功才落本地缓存）；写失败抛 5001/503，绝不静默降级。
    """
    digest = hashlib.sha256(raw).hexdigest()
    file_id = digest[:16]
    ext = (Path(filename or "").suffix or "").lower()
    if ext not in _ALLOWED_EXT:
        ext = ".bin"
    rel = _rel_dir(tenant, session_id) / f"{file_id}{ext}"
    if _use_s3() and not _s3_put(rel.as_posix(), raw):
        # 对象存储是源：写失败不回退本地盘（否则两处副本分叉、恢复时丢件），显式报错让上游可见
        raise BusinessError(
            ErrorCode.UPSTREAM_FAILED, "对象存储暂不可用，附件未能保存，请稍后重试", 503
        )
    target = _root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)  # 本地物化缓存：s3 模式回读秒开（源在对象存储），local 模式即唯一副本
    return {
        "file_id": file_id,
        "url": f"/api/v1/multimodal/media/{file_id}",
        "path": str(target),
        "sha256": digest,
    }


def _s3_put(key: str, raw: bytes) -> bool:
    """上传对象（key 与本地布局同构）；失败返回 False，由调用方决定报错口径（s3 模式转 5001）。"""
    client = _s3_client()
    if client is None:
        return False
    try:
        client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=raw)
        return True
    except Exception:  # 网络/权限/桶缺失：本次失败由调用方显式报错，绝不静默落本地盘
        return False


def resolve_path(*, tenant: str, file_id: str) -> Path | None:
    """按租户回查文件（防穿越：只认租户目录前缀）；s3 模式未命中缓存时回源物化。"""
    cleaned = (file_id or "").strip()
    if not cleaned or len(cleaned) > 64 or any(c in cleaned for c in ("/", "\\", ".")):
        return None
    tenant_dir = _root() / _safe_tenant(tenant)
    if tenant_dir.is_dir():
        hits = sorted(tenant_dir.rglob(f"{cleaned}.*"))
        if hits:
            return hits[0]
    return _s3_fetch(tenant, cleaned)


def _s3_fetch(tenant: str, file_id: str) -> Path | None:
    """S3 回源（冷路径）：url 只带 file_id，故按 `{tenant}/` 前缀找同名对象再物化到本地。

    跨租户文件不在本前缀下，自然取不到（404 语义，不泄漏他租户附件）。
    """
    if not _use_s3():
        return None
    client = _s3_client()
    if client is None:
        return None
    try:
        listed = client.list_objects_v2(
            Bucket=settings.S3_BUCKET, Prefix=f"{_safe_tenant(tenant)}/"
        )
        keys = [o["Key"] for o in listed.get("Contents", []) if Path(o["Key"]).stem == file_id]
        if not keys:
            return None
        key = sorted(keys)[0]
        target = _root() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(client.get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read())
        return target
    except Exception:  # 对象存储不可用：按「无此文件」处理（404 语义），不阻断请求
        return None
