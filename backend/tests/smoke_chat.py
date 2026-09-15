"""登录→问答→流式冒烟（对齐测试方案 §4 smoke 风格）

覆盖：POST /auth/login 取 token → GET /auth/me → POST /chat 有据/2001 拒答 →
POST /agent/chat/stream 四事件有序 + id 行 + done.session_id →
done.tool_calls/orchestration（编排接线 B 余①）→
同 client_msg_id 重发不翻倍 → GET /sessions/{id} 历史可查。
用法：python tests/smoke_chat.py [http://127.0.0.1:8000]
前置：后端已 init_db 并启动 uvicorn（默认 admin/admin123，SEED_* 覆盖时改 LOGIN_USER / LOGIN_PASS 环境变量）。
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

    # 规范路径：四事件有序 + 全帧带 id + done 带引用与 session_id（落库可查）
    body = {"query": "退货政策是什么", "client_msg_id": "smoke-e2e-1"}
    with client.stream("POST", "/api/v1/agent/chat/stream", json=body, headers=headers) as s:
        agent_lines = list(s.iter_lines())
    events = [ln.split("event: ", 1)[1] for ln in agent_lines if ln.startswith("event: ")]
    ids = [ln.split("id: ", 1)[1] for ln in agent_lines if ln.startswith("id: ")]
    check(
        "agent stream four events in order",
        events[0] == "source"
        and events[1] == "phase"
        and "message" in events
        and events[-1] == "done",
        str(events)[:200],
    )
    check(
        "agent stream every frame has unique id",
        len(ids) == len(events) and len(set(ids)) == len(ids),
        str(ids)[:200],
    )
    agent_done = ""
    for i, line in enumerate(agent_lines):
        if line.startswith("event: done") and i + 1 < len(agent_lines):
            agent_done = agent_lines[i + 1].replace("data: ", "", 1)
            break
    check(
        "agent done has refs+trace+session",
        '"references"' in agent_done
        and '"trace_id"' in agent_done
        and '"session_id"' in agent_done,
        agent_done[:200],
    )

    # 编排接线（执行步骤 B 余①）：done 透出 tool_calls/orchestration，检索段真走 kb.retrieve 连接器
    try:
        done_obj = json.loads(agent_done)
    except ValueError:
        done_obj = {}
    calls = done_obj.get("tool_calls") or []
    check(
        "done.tool_calls wired via kb.retrieve",
        any(
            isinstance(c, dict) and c.get("tool") == "kb.retrieve" and c.get("status") == "ok"
            for c in calls
        ),
        str(calls)[:200],
    )
    orch = done_obj.get("orchestration") or {}
    check(
        "done.orchestration.notes is list",
        isinstance(orch.get("notes"), list),
        str(orch)[:200],
    )
    handoff_obj = done_obj.get("handoff") or {}
    check(
        "done.handoff carries rule decision",
        isinstance(handoff_obj, dict)
        and {"hit", "code", "reason", "applied", "handoff_status"} <= set(handoff_obj),
        str(handoff_obj)[:200],
    )

    session_id = ""
    try:
        session_id = json.loads(agent_done).get("session_id", "")
    except ValueError:
        session_id = ""
    check("agent done session id parseable", bool(session_id), agent_done[:200])
    if session_id:
        detail = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
        roles = [m.get("role") for m in detail.get("data", {}).get("messages", [])]
        # 详情消息倒序（page=1 最新页），反转即正序 [user, agent]
        check(
            "history persisted user+agent",
            list(reversed(roles)) == ["user", "agent"],
            str(roles)[:200],
        )
        # 同键重发：幂等不翻倍
        with client.stream("POST", "/api/v1/agent/chat/stream", json=body, headers=headers) as s:
            list(s.iter_lines())
        detail2 = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
        check(
            "resend same key keeps 2 rows",
            len(detail2.get("data", {}).get("messages", [])) == 2,
            str(detail2)[:200],
        )

    # C 步规则表真链路：买家喊人工 → done.handoff 命中 explicit_request 且真把会话挂进待接队列
    with client.stream(
        "POST",
        "/api/v1/agent/chat/stream",
        json={"query": "我要转人工", "client_msg_id": "smoke-e2e-handoff"},
        headers=headers,
    ) as s:
        hand_lines = list(s.iter_lines())
    hand_done = ""
    for i, line in enumerate(hand_lines):
        if line.startswith("event: done") and i + 1 < len(hand_lines):
            hand_done = hand_lines[i + 1].replace("data: ", "", 1)
            break
    try:
        hit_obj = json.loads(hand_done).get("handoff") or {}
    except ValueError:
        hit_obj = {}
    check(
        "handoff rule hit explicit_request",
        hit_obj.get("hit") is True and hit_obj.get("code") == "explicit_request",
        str(hit_obj)[:200],
    )
    check(
        "handoff applied -> pending",
        hit_obj.get("applied") is True and hit_obj.get("handoff_status") == "pending",
        str(hit_obj)[:200],
    )

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
