"""可观测记录（关键链路留痕 → 内存计数器 + JSONL 落盘，对齐 FRD FR-9 + 执行步骤 E 步）

链路：问答/工具/转人工 → record(event, fields) → ①内存计数器/滑窗（GET /workbench/metrics
     即时聚合，含 30s 接起率）②后台守护线程批量落 JSONL（data/observability/
     events-YYYYMMDD.jsonl，重启不丢历史，Prometheus/Langfuse 网关后置替换只改本模块）。
红线：record() 绝不抛错、绝不阻塞主流程（入队即返回，落盘失败只丢该条事件）；
     开关/目录/接起目标秒数全进 Settings（OBSERVABILITY_* 可热更）；
     事件名与字段口径唯一出处在本文件，业务侧只传语义字段不拼字符串。
口径：接起率 = handoff.claim 距该会话 handoff(applied) 的秒差 ≤ OBSERVABILITY_ANSWER_TARGET_SECONDS
     的比例（坐席代回清零由规则表侧管，这里只度量「挂起→接起」耗时）。
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings

# ---------------- 内存态（锁保护，metrics 即时读） ----------------

_lock = threading.Lock()
_counters: dict[str, int] = {}
_flags: dict[str, int] = {}
_recent: deque[dict[str, Any]] = deque(maxlen=500)
# 会话挂起时刻（session_id → epoch 秒）：claim 时算接起耗时即弹出，防无界增长
_pending_since: dict[str, float] = {}
_answer_lat: deque[float] = deque(maxlen=500)

# ---------------- 落盘（守护线程批量写 JSONL） ----------------

_queue: queue.Queue[Any] = queue.Queue(maxsize=2000)
_writer: threading.Thread | None = None
_writer_lock = threading.Lock()


def _ensure_writer() -> None:
    """惰性起守护线程（双检锁）；OBSERVABILITY_ENABLED=false 时不起，只留内存态。"""
    global _writer
    if _writer is not None and _writer.is_alive():
        return
    with _writer_lock:
        if _writer is not None and _writer.is_alive():
            return
        _writer = threading.Thread(target=_writer_loop, name="observability-writer", daemon=True)
        _writer.start()


def _writer_loop() -> None:
    """攒批写盘：最多 50 条或 1 秒一批；队列满即丢（record 侧已保证不阻塞）。

    哨兵 ("__flush__", Event) 让 flush() 能同步等到「此前入队的事件全部落盘」。
    """
    while True:
        batch: list[tuple[float, str, dict[str, Any]]] = []
        deadline = time.time() + 1.0
        while len(batch) < 50 and time.time() < deadline:
            try:
                item = _queue.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if isinstance(item, tuple) and item and item[0] == "__flush__":
                _drain_and_write(batch)
                batch = []
                item[1].set()  # 通知 flush()：哨兵之前入队的都已写完
                deadline = time.time() + 1.0
                continue
            batch.append(item)
        _drain_and_write(batch)


def _drain_and_write(batch: list[tuple[float, str, dict[str, Any]]]) -> None:
    if not batch:
        return
    try:
        day = datetime.fromtimestamp(batch[0][0], tz=UTC).strftime("%Y%m%d")
        target = Path(settings.OBSERVABILITY_DIR) / f"events-{day}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                {"ts": round(ts, 3), "event": event, **fields},
                ensure_ascii=False,
                default=str,
            )
            for ts, event, fields in batch
        ]
        with target.open("a", encoding="utf-8") as fp:
            fp.write("\n".join(lines) + "\n")
    except OSError:
        return  # 落盘失败只丢该批事件，绝不影响业务主流程


def flush(timeout: float = 3.0) -> bool:
    """排空队列并等待写盘完成（测试/退出用；生产路径不依赖）。返回是否按时排空。"""
    if _writer is None or not _writer.is_alive():
        return False
    done = threading.Event()
    _queue.put(("__flush__", done))
    return done.wait(timeout)


# ---------------- 对外唯一出口 ----------------


def record(event: str, fields: dict[str, Any] | None = None) -> None:
    """记一条关键链路事件：内存计数即时更新，落盘入队异步完成；任何异常都不外抛。"""
    data = dict(fields or {})
    now = time.time()
    try:
        with _lock:
            _counters[event] = _counters.get(event, 0) + 1
            for key, value in data.items():
                if isinstance(value, bool) and value:
                    flag = f"{event}.{key}"
                    _flags[flag] = _flags.get(flag, 0) + 1
            _recent.append({"ts": now, "event": event, **data})
            if event == "handoff" and data.get("applied"):
                _pending_since[str(data.get("session_id") or "")] = now
            elif event == "handoff.claim":
                started = _pending_since.pop(str(data.get("session_id") or ""), None)
                if started is not None:
                    _answer_lat.append(now - started)
        if settings.OBSERVABILITY_ENABLED:
            _ensure_writer()
            with contextlib.suppress(queue.Full):
                _queue.put_nowait((now, event, data))
    except Exception:
        return


def reset() -> None:
    """清空内存态（仅测试用）。"""
    with _lock:
        _counters.clear()
        _flags.clear()
        _recent.clear()
        _pending_since.clear()
        _answer_lat.clear()


# ---------------- 聚合视图（GET /workbench/metrics 的口径） ----------------


def _percentile(sorted_values: list[float], pct: float) -> float:
    index = min(len(sorted_values) - 1, max(0, round(pct * (len(sorted_values) - 1))))
    return sorted_values[index]


def snapshot() -> dict[str, Any]:
    """当前内存态的规整聚合：事件计数 / 布尔标记计数 / 转人工接起率（FR-7 验收口径）。"""
    target = max(1, int(settings.OBSERVABILITY_ANSWER_TARGET_SECONDS))
    with _lock:
        lat = sorted(_answer_lat)
        claims = _counters.get("handoff.claim", 0)
        within = sum(1 for v in lat if v <= target)
        handoff = {
            "hits": _counters.get("handoff", 0),
            "applied": _flags.get("handoff.applied", 0),
            "pending_now": len(_pending_since),
            "claims": claims,
            "answer_measured": len(lat),
            "answer_within_target": within,
            "answer_rate": round(within / claims, 4) if claims else None,
            "answer_avg_seconds": round(sum(lat) / len(lat), 2) if lat else None,
            "answer_p95_seconds": round(_percentile(lat, 0.95), 2) if lat else None,
            "target_seconds": target,
        }
        llm_total = _counters.get("llm", 0)
        tool_total = _counters.get("agent.tool", 0)
        return {
            "enabled": bool(settings.OBSERVABILITY_ENABLED),
            "dir": settings.OBSERVABILITY_DIR,
            "counters": dict(_counters),
            "flags": dict(_flags),
            "handoff": handoff,
            "llm_ok_rate": (round(_flags.get("llm.ok", 0) / llm_total, 4) if llm_total else None),
            "tool_ok_rate": (
                round(_flags.get("agent.tool.ok", 0) / tool_total, 4) if tool_total else None
            ),
            "reject_count": _flags.get("chat.reject", 0),
        }
