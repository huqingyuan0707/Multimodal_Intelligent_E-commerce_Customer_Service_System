"""历史对话三层 E2E 冒烟（Session→Message→Context，对齐 FR-1.4 + API 规范 §4.3）

覆盖：login 取 token → 建会话 → 两轮问答（同 thread，第二轮 done.context.rounds≥1）→
GET context（摘要/预算同源）→ 详情翻页（has_more）→ 重命名 → 删除级联遗忘（404）。
用法：python tests/smoke_sessions.py [http://127.0.0.1:8000]
前置：后端已迁移（alembic upgrade head）并启动（默认 admin/admin123）。
"""

from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USERNAME = os.getenv("LOGIN_USER", "admin")
PASSWORD = os.getenv("LOGIN_PASS", "admin123")

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    """PASS/FAIL 明细行。"""
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed += 1
        print(f"FAIL: {name} {detail[:200]}")


def _done_payload(lines: list[str]) -> dict:
    for i, line in enumerate(lines):
        if line.startswith("event: done") and i + 1 < len(lines):
            try:
                return json.loads(lines[i + 1].replace("data: ", "", 1))
            except ValueError:
                return {}
    return {}


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60.0, trust_env=False)
    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("login ok", r.status_code == 200 and r.json().get("code") == 0, r.text)
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    headers = {"Authorization": f"Bearer {r.json()['data']['token']}"}

    # 建会话（标题≤20 字截断口径）
    r = client.post("/api/v1/sessions", json={"title": "冒烟三层"}, headers=headers)
    sid = (r.json().get("data") or {}).get("id", "")
    check("create session", r.json().get("code") == 0 and bool(sid), r.text)

    # 两轮同 thread：第二轮 done.context.rounds≥1（历史进 LLM 证据）
    ctx_rounds = -1
    for i in range(2):
        with client.stream(
            "POST",
            "/api/v1/agent/chat/stream",
            json={"query": "退货政策是什么", "thread_id": sid, "client_msg_id": f"smoke-3l-{i}"},
            headers=headers,
        ) as s:
            done = _done_payload(list(s.iter_lines()))
        ctx_rounds = int((done.get("context") or {}).get("rounds", -1))
    check("round2 context.rounds>=1", ctx_rounds >= 1, json.dumps(done)[:200])

    # 上下文视图同源（坐席 Trace 调试口径）
    r = client.get(f"/api/v1/sessions/{sid}/context", headers=headers)
    ctx = r.json().get("data") or {}
    check(
        "context view rounds+budget",
        ctx.get("rounds", 0) >= 1 and ctx.get("budget", 0) > 0,
        r.text,
    )

    # 列表分页对象 + 详情翻页
    r = client.get("/api/v1/sessions", params={"page": 1, "size": 20}, headers=headers)
    page = r.json().get("data") or {}
    check(
        "list pagination object",
        isinstance(page.get("items"), list) and page.get("total", 0) >= 1,
        r.text,
    )
    r = client.get(f"/api/v1/sessions/{sid}", params={"page": 1, "size": 2}, headers=headers)
    detail = r.json().get("data") or {}
    check(
        "detail paged has_more+summary",
        detail.get("has_more") is True and "summary" in detail,
        r.text,
    )

    # 重命名 + 删除级联遗忘
    r = client.put(f"/api/v1/sessions/{sid}", json={"title": "改名"}, headers=headers)
    check("rename ok", (r.json().get("data") or {}).get("title") == "改名", r.text)
    r = client.delete(f"/api/v1/sessions/{sid}", headers=headers)
    check("delete ok", r.json().get("code") == 0, r.text)
    r = client.get(f"/api/v1/sessions/{sid}", headers=headers)
    check("deleted 404", r.status_code == 404, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
