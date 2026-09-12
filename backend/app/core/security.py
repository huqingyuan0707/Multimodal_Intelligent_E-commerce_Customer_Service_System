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


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2 落库格式 ``salt$hex``，salt/迭代次数走 Settings 不硬编码。

    注意：迭代次数一经调整，存量 ``pwd_hash`` 将验不过，需同步重刷用户密码。
    """
    raw_salt = salt or os.urandom(settings.PASSWORD_SALT_BYTES).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        raw_salt.encode(),
        settings.PASSWORD_HASH_ITERATIONS,
    )
    return f"{raw_salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """等长比较防时序攻击，格式非法直接返回 False。"""
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def split_roles(raw: str) -> list[str]:
    """角色文本解析唯一口径：`"cs,kb" -> ["cs","kb"]`，分隔符走 Settings。"""
    return [r.strip() for r in raw.split(settings.ROLES_SEPARATOR) if r.strip()]


def issue_token(username: str, tenant: str, roles: list[str]) -> str:
    """签发 JWT（sub/tenant/roles/iat/exp/jti，算法走 Settings）。"""
    now = int(time.time())
    payload = {
        "sub": username,
        "tenant": tenant,
        "roles": roles,
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_EXPIRE_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )


def decode_token(token: str) -> dict[str, object]:
    """验签并校验有效期，失败抛 ValueError（调用方转 401）。"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Token 非法") from exc
