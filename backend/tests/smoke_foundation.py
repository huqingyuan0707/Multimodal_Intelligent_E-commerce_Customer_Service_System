"""前置地基验收冒烟（对齐本任务验收口径）

覆盖：登录拿 token → /auth/me 身份 → 401 信封码（无 token/伪造）→ /auth/switch
代入切自己成功拿新 token 并验身份、幽灵用户 404 → sessions/tasks/documents
真实空数据不报错（列表 200 数组、建/查/删闭环、跨租户 404）→ 未知路由 404 信封。
用法：python tests/smoke_foundation.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

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
        print(f"FAIL: {name} {detail}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=15.0, trust_env=False)

    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    body = r.json()
    check("login ok", r.status_code == 200 and body["code"] == 0, r.text[:200])
    if body.get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    token = body["data"]["token"]
    auth = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/auth/me", headers=auth).json()
    check(
        "me has name+tenant+roles+perms",
        me["code"] == 0
        and bool(me["data"]["name"])
        and bool(me["data"]["tenant"])
        and bool(me["data"]["roles"])
        and bool(me["data"]["perms"]),
        str(me)[:200],
    )

    # 401 统一信封：无 token 与伪造 token 均 401 + 1002（前端凭此走 handle401）
    r = client.get("/api/v1/auth/me")
    check(
        "401 envelope without token",
        r.status_code == 401 and r.json().get("code") == 1002,
        r.text[:200],
    )
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged.token.value"})
    check(
        "401 envelope forged token",
        r.status_code == 401 and r.json().get("code") == 1002,
        r.text[:200],
    )

    # 代入切换：admin 切自己成功拿新 token（审计同事务），幽灵用户 404
    sw = client.post("/api/v1/auth/switch", headers=auth, json={"username": USERNAME}).json()
    check(
        "switch self ok with new token",
        sw.get("code") == 0 and bool((sw.get("data") or {}).get("token")),
        str(sw)[:200],
    )
    if sw.get("code") == 0:
        sw_me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {sw['data']['token']}"},
        ).json()
        check(
            "switch token identity matches",
            sw_me.get("data", {}).get("name") == USERNAME,
            str(sw_me)[:200],
        )
    ghost = client.post("/api/v1/auth/switch", headers=auth, json={"username": "ghost"})
    check(
        "switch ghost 404/1004",
        ghost.status_code == 404 and ghost.json().get("code") == 1004,
        ghost.text[:200],
    )

    # sessions 真实闭环
    r = client.get("/api/v1/sessions", headers=auth)
    check(
        "sessions list 200 array",
        r.status_code == 200 and isinstance(r.json()["data"], list),
        r.text[:200],
    )
    created = client.post("/api/v1/sessions", headers=auth, json={"title": "冒烟会话"}).json()
    sid = (created.get("data") or {}).get("id", "")
    check("sessions create returns id", created.get("code") == 0 and bool(sid), str(created)[:200])
    if sid:
        detail = client.get(f"/api/v1/sessions/{sid}", headers=auth).json()
        check(
            "sessions detail has messages",
            detail.get("code") == 0 and isinstance(detail["data"].get("messages"), list),
            str(detail)[:200],
        )
        deleted = client.delete(f"/api/v1/sessions/{sid}", headers=auth).json()
        check("sessions delete ok", deleted.get("code") == 0, str(deleted)[:200])
    missing = client.get("/api/v1/sessions/no-such-id", headers=auth)
    check(
        "sessions missing 404/1004",
        missing.status_code == 404 and missing.json().get("code") == 1004,
        missing.text[:200],
    )

    # tasks 真实闭环
    r = client.get("/api/v1/tasks", headers=auth)
    check(
        "tasks list 200 array",
        r.status_code == 200 and isinstance(r.json()["data"], list),
        r.text[:200],
    )
    created = client.post(
        "/api/v1/tasks", headers=auth, json={"type": "smoke", "payload": {}}
    ).json()
    tid = (created.get("data") or {}).get("task_id", "")
    check(
        "tasks create returns task_id", created.get("code") == 0 and bool(tid), str(created)[:200]
    )
    if tid:
        one = client.get(f"/api/v1/tasks/{tid}", headers=auth).json()
        check("tasks get ok", one.get("code") == 0, str(one)[:200])

    # documents 真实空数据 + 去重
    r = client.get("/api/v1/documents", headers=auth)
    check(
        "documents list 200 page",
        r.status_code == 200 and isinstance(r.json()["data"].get("items"), list),
        r.text[:200],
    )
    up1 = client.post(
        "/api/v1/documents/upload",
        headers=auth,
        files={"file": ("smoke.txt", b"smoke-foundation")},
    ).json()
    check("documents upload ok", up1.get("code") == 0 and up1["data"].get("doc_id"), str(up1)[:200])
    up2 = client.post(
        "/api/v1/documents/upload",
        headers=auth,
        files={"file": ("smoke.txt", b"smoke-foundation")},
    ).json()
    check(
        "documents dedup skipped",
        up2.get("code") == 0 and up2["data"].get("skipped") is True,
        str(up2)[:200],
    )
    if up1.get("data", {}).get("doc_id"):
        client.delete(f"/api/v1/documents/{up1['data']['doc_id']}", headers=auth)

    # 参数校验统一 1001
    r = client.post("/api/v1/tasks", headers=auth, json={"type": "  ", "payload": {}})
    check("tasks empty type 1001", r.json().get("code") == 1001, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
