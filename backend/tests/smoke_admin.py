"""管理后台冒烟（对齐测试方案 §4 smoke 风格）

覆盖：login → overview → 建租户 → 重复建 1001 → 改配额 → 非法配额 1001 →
  停服 → 用户列表 → 审计列表含 tenant.create。
用法：python tests/smoke_admin.py [http://127.0.0.1:8000]
账号走环境变量 LOGIN_USER/LOGIN_PASS（默认 admin/admin123，取 Settings 种子）。
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


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, trust_env=False)
    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("login ok", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    headers = {"Authorization": f"Bearer {r.json()['data']['token']}"}

    r = client.get("/api/v1/admin/overview", headers=headers)
    check("overview ok", r.json().get("code") == 0, r.text[:200])

    code = f"smoke-{int(time.time())}"
    r = client.post(
        "/api/v1/admin/tenants",
        json={"code": code, "name": "冒烟租户", "plan": "trial"},
        headers=headers,
    )
    check("tenant create", r.json().get("code") == 0, r.text[:200])
    r = client.post(
        "/api/v1/admin/tenants",
        json={"code": code, "name": "重复"},
        headers=headers,
    )
    check("tenant dup 1001", r.json().get("code") == 1001, r.text[:200])

    r = client.put(
        f"/api/v1/admin/tenants/{code}/quota",
        json={"quota_tokens": 5000, "quota_concurrency": 10},
        headers=headers,
    )
    check("quota ok", r.json().get("code") == 0, r.text[:200])
    r = client.put(
        f"/api/v1/admin/tenants/{code}/quota",
        json={"quota_tokens": 0, "quota_concurrency": 1},
        headers=headers,
    )
    check("quota 1001", r.json().get("code") == 1001, r.text[:200])

    r = client.post(
        f"/api/v1/admin/tenants/{code}/status",
        json={"status": "suspended"},
        headers=headers,
    )
    check("suspend ok", r.json().get("code") == 0, r.text[:200])

    r = client.get("/api/v1/admin/users", headers=headers, params={"page": 1, "size": 20})
    check("users ok", r.json().get("code") == 0, r.text[:200])

    r = client.get(
        "/api/v1/admin/audits", headers=headers, params={"tenant": code, "page": 1, "size": 20}
    )
    body = r.json()
    actions = [a.get("action") for a in (body.get("data") or {}).get("items", [])]
    check("audit has create", body.get("code") == 0 and "tenant.create" in actions, r.text[:300])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
