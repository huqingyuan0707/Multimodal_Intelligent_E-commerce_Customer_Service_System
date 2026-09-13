"""文档解析服务（上传第 2 步，对齐 RAG 规范 §1）

链路：上传原始字节 → 解码 → 清洗 → 元数据提取 → 交切分/向量化。
红线：阻塞解码走 to_thread；租户由调用方显式传参；超限 1001 中文提示。
"""

from __future__ import annotations

import hashlib

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode

# ---------------- 解析 ----------------


def decode_bytes(raw: bytes) -> str:
    """多编码解码：utf-8 优先，失败回退 gbk，均失败则忽略错误（纯函数可单测）。"""
    if not raw:
        return ""
    capped = raw[: settings.MAX_UPLOAD_BYTES + 1024]
    for encoding in ("utf-8", "gbk"):
        try:
            return capped.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return capped.decode("utf-8", errors="ignore")


def clean_text(text: str) -> str:
    """清洗：去 HTML 注释行/BOM/尾空格，空行压缩到单空行（纯函数可单测）。"""
    no_bom = (text or "").lstrip("\ufeff")
    kept: list[str] = []
    blank = False
    for line in no_bom.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--"):
            continue
        if not stripped:
            if not blank:
                kept.append("")
            blank = True
            continue
        blank = False
        kept.append(line.rstrip())
    return "\n".join(kept).strip() + ("\n" if kept else "")


def check_size(raw: bytes, filename: str) -> None:
    """上传大小门禁：超 MAX_UPLOAD_BYTES 直接 1001（中文可操作）。"""
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"文件 {filename or '未命名'} 超过 {settings.MAX_UPLOAD_BYTES // 1024 // 1024}M 上限，请压缩后重试",
        )


def parse_upload(filename: str, raw: bytes) -> dict[str, str]:
    """解析主入口（同步纯逻辑，调用方必须包 asyncio.to_thread）。

    返回 {title, content, sha256}：title 取文件名去后缀；content 清洗后截断到
    MAX_UPLOAD_CHARS；sha256 按原始字节算（去重口径与存量一致）。
    """
    name = (filename or "").strip() or "未命名文档"
    check_size(raw, name)
    digest = hashlib.sha256(raw).hexdigest()
    text = clean_text(decode_bytes(raw)[: settings.MAX_UPLOAD_CHARS])
    stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem.rsplit(".", 1)[0].strip() or "未命名文档"
    return {"title": stem[:200], "content": text, "sha256": digest}
