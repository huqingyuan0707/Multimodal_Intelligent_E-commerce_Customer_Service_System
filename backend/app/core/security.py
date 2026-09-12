"""密码与 Token（PBKDF2 + JWT，对齐 API 规范 §3/§4.1）

链路：auth_service 验密 → issue_token → rbac.get_current_user 解码验签。
无三方密码库依赖，哈希走标准库 hashlib；JWT 走 PyJWT。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid

import jwt

from app.config import settings

_EXPIRES_IN = 8 * 3600


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2 落库格式 ``salt$hex``，salt 缺省随机 16 字节。"""
    raw_salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw_salt.encode(), 100_000)
    return f"{raw_salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """等长比较防时序攻击，格式非法直接返回 False。"""
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def issue_token(username: str, tenant: str, roles: list[str]) -> str:
    """签发 HS256 JWT（sub/tenant/roles/iat/exp/jti）。"""
    now = int(time.time())
    payload = {
        "sub": username,
        "tenant": tenant,
        "roles": roles,
        "iat": now,
        "exp": now + _EXPIRES_IN,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm="HS256")


def decode_token(token: str) -> dict[str, object]:
    """验签并校验有效期，失败抛 ValueError（调用方转 401）。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Token 非法") from exc
