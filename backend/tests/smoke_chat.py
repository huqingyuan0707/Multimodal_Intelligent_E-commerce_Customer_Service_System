"""登录→问答→流式冒烟（对齐测试方案 §4 smoke 风格）

覆盖：POST /auth/login 取 token → GET /auth/me → POST /chat 有据/2001 拒答 → POST /chat/stream 解析 done 帧。
用法：python tests/smoke_chat.py [http://127.0.0.1:8000]
前置：后端已 init_db 并启动 uvicorn（默认 admin/admin123，SEED_* 覆盖时改 LOGIN_USER / LOGIN_PASS 环境变量）。
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
    client = httpx.Client(base_url=BASE, timeout=30.0, trust_env=False)
    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("login ok", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    token = r.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": "wrong"})
    check("login wrong 401", r.status_code == 401, r.text[:200])

    r = client.get("/api/v1/auth/me", headers=headers)
    check("me ok", r.json().get("code") == 0, r.text[:200])

    r = client.post("/api/v1/chat", json={"query": "退货政策是什么"}, headers=headers)
    body = r.json()
    check(
        "chat ok with refs",
        body.get("code") == 0 and bool(body["data"].get("references")),
        r.text[:200],
    )

    r = client.post("/api/v1/chat", json={"query": "今天天气怎么样"}, headers=headers)
    check("chat 2001 reject", r.json().get("code") == 2001, r.text[:200])

    done_payload = ""
    with client.stream(
        "POST", "/api/v1/chat/stream", json={"query": "退货政策是什么"}, headers=headers
    ) as s:
        lines = list(s.iter_lines())
    for i, line in enumerate(lines):
        if line.startswith("event: done") and i + 1 < len(lines):
            done_payload = lines[i + 1].replace("data: ", "", 1)
            break
    check("stream done has trace", '"trace_id"' in done_payload, done_payload[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
