"""可观测记录单测（E 步：计数器 / 接起耗时 / JSONL 落盘 / 异常安全，对齐 FRD FR-9）

链路：纯逻辑直测——observability 是全站关键链路留痕唯一出口，本文件保证
      「record 不抛错、计数即时、挂起→接起耗时进滑窗、flush 真落盘」不被改坏。
运行（backend/ 目录）：pytest tests/test_observability.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.core import observability


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每例独立：内存清零 + 落盘目录指到临时路径（开关默认开）。"""
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_DIR", str(tmp_path / "obs"))
    observability.reset()
    yield
    observability.reset()


def test_counters_and_flags() -> None:
    """record 即计数：事件总数 + 布尔真标记各记各的；未记事件不在计数里。"""
    observability.record("chat", {"trace_id": "t1", "refs": 3})
    observability.record("chat", {"trace_id": "t2", "reject": True})
    snap = observability.snapshot()
    assert snap["counters"]["chat"] == 2
    assert snap["flags"]["chat.reject"] == 1
    assert "chat.refs" not in snap["flags"]  # 非布尔字段不进标记


def test_handoff_answer_latency_pipeline() -> None:
    """接起率口径：handoff(applied) 记挂起时刻 → handoff.claim 算耗时进滑窗。"""
    observability.record("handoff", {"session_id": "s1", "applied": True})
    observability.record("handoff.claim", {"session_id": "s1", "assignee": "cs1"})
    observability.record("handoff", {"session_id": "s2", "applied": True})  # 未接起
    handoff = observability.snapshot()["handoff"]
    assert handoff["claims"] == 1
    assert handoff["answer_measured"] == 1
    assert handoff["pending_now"] == 1
    assert handoff["answer_within_target"] == 1
    assert handoff["answer_rate"] == 1.0  # 同秒挂起接起，必在 30s 目标内


def test_flush_writes_jsonl(tmp_path: Path) -> None:
    """flush 同步等到落盘：JSONL 每行一事件，字段原样、中文不转义。"""
    observability.record("handoff", {"session_id": "s9", "applied": True, "rule": "no_evidence"})
    assert observability.flush(timeout=5.0) is True
    files = list((tmp_path / "obs").glob("events-*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert any(r.get("event") == "handoff" and r.get("session_id") == "s9" for r in rows)


def test_record_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """红线：落盘炸了也不影响业务——目录不可写时 record 正常返回、计数照常。"""
    monkeypatch.setattr(settings, "OBSERVABILITY_DIR", "\x00illegal")
    observability.record("llm", {"ok": True})  # 不抛
    assert observability.snapshot()["counters"]["llm"] == 1


def test_disabled_skips_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """开关关：内存计数照常，但不建目录不落盘（record 入队前判开关）。"""
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)
    observability.record("agent.tool", {"ok": False})
    snap = observability.snapshot()
    assert snap["counters"]["agent.tool"] == 1
    assert snap["enabled"] is False
    assert not (tmp_path / "obs").exists()
