"""登录链路冒烟（对齐测试评估验收方案.md §4 smoke 风格）

覆盖：健康检查 → 空账号 400(1001) → 错密码 401(1002) → 正确登录拿 token/user/perms
      → GET /auth/me（带 token 200 / 无 token 401 / 伪造 token 401）→ POST /auth/logout。
用法：python tests/smoke_auth.py [http://127.0.0.1:8000]
前置：后端已启动（SEED_ON_START 默认 true 会自动灌种子；关掉则先跑 scripts/init_db.py）。
账号可用环境变量 LOGIN_USER / LOGIN_PASS 覆盖，默认 admin / admin123。
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

    r = client.get("/health")
    check("health ok", r.status_code == 200 and r.json().get("status") == "ok", r.text[:200])

    r = client.post("/api/v1/auth/login", json={"username": "  ", "password": ""})
    check(
        "login empty params 400/1001",
        r.status_code == 400 and r.json()["code"] == 1001,
        r.text[:200],
    )

    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": "wrong"})
    body = r.json()
    check(
        "login wrong pwd 401/1002",
        r.status_code == 401 and body["code"] == 1002 and bool(body["msg"]),
        r.text[:200],
    )

    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    body = r.json()
    check("login ok", r.status_code == 200 and body["code"] == 0, r.text[:200])
    if body.get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    data = body["data"]
    token = data["token"]
    check("login returns token", bool(token), "")
    check(
        "login user has tenant+roles+perms",
        bool(data["user"]["tenant"])
        and bool(data["user"]["roles"])
        and bool(data["user"]["perms"]),
        str(data["user"]),
    )

    auth = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/v1/auth/me", headers=auth)
    me = r.json()
    check(
        "me ok & identity matches",
        r.status_code == 200 and me["code"] == 0 and me["data"]["name"] == USERNAME,
        r.text[:200],
    )

    r = client.get("/api/v1/auth/me")
    check("me without token 401", r.status_code == 401, r.text[:200])

    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged.token.value"})
    check("me forged token 401", r.status_code == 401, r.text[:200])

    # 受保护业务接口：带 token 应放行（不是 401），证明登录态可用
    r = client.get("/api/v1/sessions", headers=auth)
    check("protected api with token not 401", r.status_code != 401, r.text[:200])

    r = client.post("/api/v1/auth/logout", headers=auth)
    check("logout ok", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])

    r = client.post("/api/v1/auth/logout")
    check("logout without token 401", r.status_code == 401, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
