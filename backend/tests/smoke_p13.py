"""营销/评价/工单/物流冒烟（对齐测试方案 §4 smoke 风格）

覆盖：login → 建活动 → 发券 → 同键重放 → 预算耗尽 3006 → 会员调分 →
  差评入库 → 回复 → 建工单 → 关闭 → 物流公司/单号查无。
用法：python tests/smoke_p13.py [http://127.0.0.1:8020]
账号走环境变量 LOGIN_USER/LOGIN_PASS（默认 admin/admin123，取 Settings 种子）。
"""

from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
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

    name = f"smoke-{int(time.time())}"
    r = client.post(
        "/api/v1/promos", json={"name": name, "budget": 1, "total": 10}, headers=headers
    )
    check("promo create", r.json().get("code") == 0, r.text[:200])
    promo_id = r.json()["data"]["id"] if r.json().get("code") == 0 else ""

    h = {**headers, "Idempotency-Key": f"smoke-{promo_id}"}
    r = client.post(f"/api/v1/promos/{promo_id}/grant", json={"user_ref": "u-smoke"}, headers=h)
    first_id = r.json()["data"]["id"] if r.json().get("code") == 0 else ""
    check("grant ok", bool(first_id), r.text[:200])
    r = client.post(f"/api/v1/promos/{promo_id}/grant", json={"user_ref": "u-smoke"}, headers=h)
    check(
        "grant replay",
        r.json().get("code") == 0 and r.json()["data"]["id"] == first_id,
        r.text[:200],
    )
    r = client.post(
        f"/api/v1/promos/{promo_id}/grant",
        json={"user_ref": "u-other"},
        headers={**headers, "Idempotency-Key": f"smoke-{promo_id}-2"},
    )
    check("grant 3006 exhausted", r.json().get("code") == 3006, r.text[:200])
    # 风控黑名单拦截（3007）：buyer-2077 是种子里的已复核 blocked 买家（账号关联），
    # 守卫置于预算扣减前——即便预算已耗尽也应先回 3007 而非 3006。
    r = client.post(
        f"/api/v1/promos/{promo_id}/grant",
        json={"user_ref": "buyer-2077"},
        headers={**headers, "Idempotency-Key": f"smoke-{promo_id}-3"},
    )
    check("grant 3007 risk blocked", r.json().get("code") == 3007, r.text[:200])

    r = client.post("/api/v1/members/u-smoke/points", json={"delta": 1500}, headers=headers)
    check(
        "member points",
        r.json().get("code") == 0 and r.json()["data"]["level"] == "v1",
        r.text[:200],
    )

    r = client.post(
        "/api/v1/reviews",
        json={"platform": "tb", "outer_id": "smoke-o1", "level": "bad", "content": "冒烟差评"},
        headers=headers,
    )
    review_id = r.json()["data"]["id"] if r.json().get("code") == 0 else ""
    check("review create", bool(review_id), r.text[:200])
    r = client.post(
        f"/api/v1/reviews/{review_id}/reply", json={"reply": "非常抱歉，已跟进"}, headers=headers
    )
    check("review reply", r.json().get("code") == 0, r.text[:200])
    r = client.post(
        f"/api/v1/reviews/{review_id}/ticket", json={"assignee": "cs1"}, headers=headers
    )
    ticket_id = r.json()["data"]["ticket"]["id"] if r.json().get("code") == 0 else ""
    check("review ticket", bool(ticket_id), r.text[:200])
    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close", json={"conclusion": "冒烟关闭"}, headers=headers
    )
    check("ticket close", r.json().get("code") == 0, r.text[:200])

    r = client.get("/api/v1/logistics/companies", headers=headers)
    check("companies ok", r.json().get("code") == 0 and len(r.json()["data"]) > 0, r.text[:200])
    r = client.post("/api/v1/logistics/track", json={"tracking_no": "NO-SUCH-NO"}, headers=headers)
    check("track 404", r.json().get("code") == 1004, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
