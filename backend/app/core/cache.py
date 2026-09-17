"""Redis 适配层（缓存/限流/幂等统一入口，对齐数据模型文档 §4 键规范）

链路：endpoints/services → cache.allow/get_json/set_json → Redis（INCR+EXPIRE / SETEX）
      → 依赖缺失或命令失败即 sticky 降级为进程内 TTL dict（单进程演示可用，绝不 500）。
红线：业务代码不直连 redis 客户端；键口径 `rl:{tenant}:{username}:{api}` 等取自 §4 表；
      连接超时收紧 0.5s，首败即降级不再逐请求试连；status() 供 /governance/status 巡检。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.config import settings

_lock = threading.Lock()
_off = False  # sticky 降级标记：连不上/依赖缺失后不再逐请求试连
_connected = False  # 至少成功执行过一次 Redis 命令
_mem: dict[str, tuple[float, Any]] = {}  # key → (过期时间, 值)
_holder: dict[str, Any] = {}  # 惰性客户端单例


async def _get_redis() -> Any:
    """取 Redis 异步客户端（redis.asyncio 懒 import：未装依赖也能以降级态跑）。"""
    global _off
    if _off:
        return None
    if "c" not in _holder:
        try:
            import redis.asyncio as aioredis

            _holder["c"] = aioredis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=True,
            )
        except Exception:  # 依赖缺失/构造失败 → sticky 降级（可选依赖，绝不打断请求）
            _off = True
            return None
    return _holder["c"]


def _mem_incr(key: str, window: int) -> int:
    """内存窗口计数（降级路径）：过期即重开窗口。"""
    now = time.time()
    with _lock:
        expire, val = _mem.get(key, (0.0, 0))
        if expire <= now:
            val, expire = 0, now + window
        val += 1
        _mem[key] = (expire, val)
        return int(val)


def _mem_get(key: str) -> Any:
    now = time.time()
    with _lock:
        expire, val = _mem.get(key, (0.0, None))
        if expire <= now:
            _mem.pop(key, None)
            return None
        return val


def _mem_set(key: str, value: Any, ttl: int) -> None:
    with _lock:
        _mem[key] = (time.time() + ttl, value)


async def incr_window(key: str, window_seconds: int) -> int:
    """窗口计数（Redis INCR+首次 EXPIRE；键见数据模型 §4 限流行），失败收敛内存路径。"""
    global _off, _connected
    r = await _get_redis()
    if r is not None:
        try:
            n = int(await r.incr(key))
            if n == 1:
                await r.expire(key, window_seconds)
            _connected = True
            return n
        except Exception:
            _off = True
    return _mem_incr(key, window_seconds)


async def allow(key: str, limit: int, window_seconds: int) -> bool:
    """限流判定：窗口内计数 < limit 放行。limit<=0 视为关闭限流（全放行）。"""
    if limit <= 0:
        return True
    return await incr_window(key, window_seconds) <= limit


async def get_json(key: str) -> Any:
    """读 JSON 值（幂等结果/热点缓存共用；miss 返回 None）。"""
    global _off
    r = await _get_redis()
    if r is not None:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            _off = True
    return _mem_get(key)


async def set_json(key: str, value: Any, ttl: int) -> None:
    """写 JSON 值带 TTL（幂等 24h / 缓存 10min-1h，见 §4）。"""
    global _off
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
            return
        except Exception:
            _off = True
    _mem_set(key, value, ttl)


async def delete(key: str) -> None:
    """删键（记忆遗忘用；Redis DEL + 内存弹出，失败静默，绝不打断删除主流程）。"""
    global _off
    r = await _get_redis()
    if r is not None:
        try:
            await r.delete(key)
            return
        except Exception:
            _off = True
    with _lock:
        _mem.pop(key, None)


async def scan_delete(prefix: str, limit: int = 500) -> int:
    """按前缀清扫（用户级遗忘扫线程快照；Redis SCAN 分批，内存遍历；返回删除数）。"""
    global _off
    removed = 0
    r = await _get_redis()
    if r is not None:
        try:
            async for key in r.scan_iter(match=f"{prefix}*", count=100):
                await r.delete(key)
                removed += 1
                if removed >= limit:
                    break
            return removed
        except Exception:
            _off = True
    with _lock:
        for key in [k for k in _mem if k.startswith(prefix)]:
            _mem.pop(key, None)
            removed += 1
            if removed >= limit:
                break
    return removed


def reset() -> None:
    """测试夹具：清降级粘性与内存窗口（不触碰真 Redis）。"""
    global _off, _connected
    with _lock:
        _off = False
        _connected = False
        _mem.clear()
        _holder.clear()


def status() -> dict[str, Any]:
    """治理巡检口径（/governance/status）：backend=redis/memory + 是否处于降级。"""
    return {
        "backend": "memory" if _off else ("redis" if _connected else "redis-pending"),
        "available": _connected,
        "degraded": _off,
        "url_set": bool(settings.REDIS_URL),
        "mem_keys": len(_mem),
    }
