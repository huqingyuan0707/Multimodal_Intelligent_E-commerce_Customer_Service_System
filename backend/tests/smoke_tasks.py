"""任务中心联调冒烟（对齐 API 规范 §4.5 + 页面设计 §3.3）

覆盖：登录拿 token → 建 reindex 任务拿 task_id → 轮询 60s 内 running→done
→ 列表含该任务 → 详情 result 含 docs/chunks → 建演示任务同样跑完。
用法：python tests/smoke_tasks.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import os
import sys
import time

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
        print(f"FAIL: {name} {detail}")


def wait_done(client: httpx.Client, auth: dict[str, str], tid: str, timeout: int = 60) -> dict:
    """轮询任务详情直到终态（done/error）或超时。"""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get(f"/api/v1/tasks/{tid}", headers=auth).json()
        if (last.get("data") or {}).get("status") in ("done", "error"):
            break
        time.sleep(2)
    return last


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=15.0, trust_env=False)

    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    body = r.json()
    check("login ok", r.status_code == 200 and body.get("code") == 0, r.text[:200])
    if body.get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    auth = {"Authorization": f"Bearer {body['data']['token']}"}

    created = client.post("/api/v1/tasks", headers=auth, json={"type": "reindex"}).json()
    tid = (created.get("data") or {}).get("task_id", "")
    check("create reindex returns task_id", created.get("code") == 0 and bool(tid), str(created)[:200])
    if not tid:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1

    final = wait_done(client, auth, tid)
    data = final.get("data") or {}
    check("reindex reaches done", data.get("status") == "done", str(final)[:300])
    result = data.get("result") or {}
    check("reindex result has docs/chunks", "docs" in result and "chunks" in result, str(result)[:200])

    listed = client.get("/api/v1/tasks", headers=auth, params={"page": 1, "size": 20}).json()
    items = listed.get("data") or []
    check("list contains task", any((t.get("task_id") == tid) for t in items), str(listed)[:200])

    demo = client.post("/api/v1/tasks", headers=auth, json={"type": "import"}).json()
    dtid = (demo.get("data") or {}).get("task_id", "")
    check("create import returns task_id", demo.get("code") == 0 and bool(dtid), str(demo)[:200])
    if dtid:
        dfinal = wait_done(client, auth, dtid)
        check("import reaches done", (dfinal.get("data") or {}).get("status") == "done", str(dfinal)[:300])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
