"""坐席工作台联调冒烟（对齐 API 规范 §4.11 + 页面设计 §3.2）

覆盖：登录拿 token → 建会话 → 转人工进队列 → 认领 → 内部备注写读 → 坐席代回落 agent 行
→ 坐席 Trace（会话态/消息/上下文用量三段齐）→ 解决归档 + resolved 过滤 → 无 token 401。
用法：python tests/smoke_workbench.py [http://127.0.0.1:8000]
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
    check("login ok", r.status_code == 200 and body.get("code") == 0, r.text[:200])
    if body.get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    auth = {"Authorization": f"Bearer {body['data']['token']}"}

    # 无 token 访问队列必须 401（路由级鉴权生效）
    check("queue rejects anonymous", client.get("/api/v1/workbench/queue").status_code == 401)

    # 转人工触发规则表（C 步）：坐席可读规则清单 + 阈值，匿名 401（判据口径唯一出口在服务端）
    rules = client.get("/api/v1/workbench/handoff-rules", headers=auth).json()
    rules_data = rules.get("data") or {}
    codes = {row.get("code") for row in rules_data.get("rules") or []}
    check(
        "handoff rules listed for agent",
        rules.get("code") == 0
        and rules_data.get("enabled") is True
        and {"explicit_request", "negative_sentiment", "no_evidence", "miss_streak"} <= codes
        and int(rules_data.get("miss_streak_threshold") or 0) >= 1,
        str(rules)[:240],
    )
    check(
        "handoff rules reject anonymous",
        client.get("/api/v1/workbench/handoff-rules").status_code == 401,
    )

    created = client.post("/api/v1/sessions", headers=auth, json={"title": "联调冒烟-工作台"})
    sid = ((created.json().get("data") or {}) if created.status_code == 200 else {}).get("id", "")
    check("create session returns id", bool(sid), created.text[:200])
    if not sid:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1

    handed = client.post(
        f"/api/v1/workbench/sessions/{sid}/handoff",
        headers=auth,
        json={"reason": "联调冒烟：要人工"},
    ).json()
    check(
        "handoff -> pending",
        handed.get("code") == 0 and (handed.get("data") or {}).get("handoff_status") == "pending",
        str(handed)[:240],
    )

    queue = client.get(
        "/api/v1/workbench/queue", headers=auth, params={"status": "pending", "page": 1, "size": 20}
    ).json()
    data = queue.get("data") or {}
    hit = [x for x in (data.get("items") or []) if x.get("id") == sid]
    check("queue lists pending session", queue.get("code") == 0 and bool(hit), str(queue)[:240])
    check(
        "queue row carries label/username",
        bool(hit) and hit[0].get("handoff_label") == "待接" and bool(hit[0].get("username")),
        str(hit)[:200],
    )

    claimed = client.post(f"/api/v1/workbench/sessions/{sid}/claim", headers=auth).json()
    cdata = claimed.get("data") or {}
    check(
        "claim -> handling + assignee",
        claimed.get("code") == 0
        and cdata.get("handoff_status") == "handling"
        and cdata.get("assignee") == USERNAME,
        str(claimed)[:240],
    )

    note = client.post(
        f"/api/v1/workbench/sessions/{sid}/notes", headers=auth, json={"content": "联调冒烟备注"}
    ).json()
    check(
        "add note ok",
        note.get("code") == 0 and (note.get("data") or {}).get("author") == USERNAME,
        str(note)[:200],
    )
    notes = client.get(f"/api/v1/workbench/sessions/{sid}/notes", headers=auth).json()
    check(
        "list notes contains new one",
        notes.get("code") == 0
        and any(n.get("content") == "联调冒烟备注" for n in notes.get("data") or []),
        str(notes)[:200],
    )

    reply = client.post(
        f"/api/v1/workbench/sessions/{sid}/reply",
        headers=auth,
        json={"content": "坐席已接管，正在为您处理（联调冒烟）"},
    ).json()
    rdata = reply.get("data") or {}
    check(
        "agent reply persisted",
        reply.get("code") == 0
        and rdata.get("role") == "agent"
        and bool(rdata.get("trace_id"))
        and bool(rdata.get("id")),
        str(reply)[:240],
    )

    trace = client.get(f"/api/v1/workbench/sessions/{sid}/trace", headers=auth).json()
    tdata = trace.get("data") or {}
    ctx = tdata.get("context") or {}
    check(
        "trace has session/messages/context",
        trace.get("code") == 0
        and (tdata.get("session") or {}).get("handoff_status") == "handling"
        and any(m.get("id") == rdata.get("id") for m in tdata.get("messages") or [])
        and {"rounds", "tokens", "budget"} <= set(ctx),
        str(trace)[:300],
    )

    resolved = client.post(
        f"/api/v1/workbench/sessions/{sid}/resolve",
        headers=auth,
        json={"conclusion": "联调冒烟完成"},
    ).json()
    check(
        "resolve -> resolved",
        resolved.get("code") == 0
        and (resolved.get("data") or {}).get("handoff_status") == "resolved",
        str(resolved)[:240],
    )
    again = client.post(f"/api/v1/workbench/sessions/{sid}/resolve", headers=auth).json()
    check("resolve twice blocked", again.get("code") == 1001, str(again)[:200])
    done_queue = client.get(
        "/api/v1/workbench/queue", headers=auth, params={"status": "resolved"}
    ).json()
    check(
        "resolved filter lists it",
        done_queue.get("code") == 0
        and any(x.get("id") == sid for x in (done_queue.get("data") or {}).get("items") or []),
        str(done_queue)[:240],
    )
    open_queue = client.get(
        "/api/v1/workbench/queue", headers=auth, params={"status": "open"}
    ).json()
    check(
        "open filter excludes it",
        open_queue.get("code") == 0
        and not any(x.get("id") == sid for x in (open_queue.get("data") or {}).get("items") or []),
        str(open_queue)[:240],
    )

    print(f"RESULT: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
