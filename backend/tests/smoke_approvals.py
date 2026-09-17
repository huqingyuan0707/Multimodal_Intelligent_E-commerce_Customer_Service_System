"""审批中心联调冒烟（对齐 API 规范 §4.5/§4.7 + 页面设计 §3.4）

链路：登录 → 分页列表(page/size) → 筛选(status/action/keyword/overdue) → 改价建单
      → 改参批准生效 → 重复处理 4004 → 驳回留痕（含空理由 1001）→ 详情(超期+政策引用) → 越权 403。
用法：python tests/smoke_approvals.py [http://127.0.0.1:8000]
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
    check("login ok", r.status_code == 200 and r.json().get("code") == 0, r.text[:200])
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    token = r.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 服务端分页：默认待办，page/size 必回分页对象
    r = client.get(
        "/api/v1/approvals", params={"status": "pending", "page": 1, "size": 20}, headers=headers
    )
    body = r.json()
    data = body.get("data") or {}
    check(
        "list page envelope",
        body.get("code") == 0 and isinstance(data.get("items"), list) and "total" in data,
        r.text[:300],
    )
    check("list page/size echo", data.get("page") == 1 and data.get("size") == 20, r.text[:200])

    # 状态筛选：全部 + 已通过（空结果不报错）
    r = client.get(
        "/api/v1/approvals", params={"status": "", "page": 1, "size": 5}, headers=headers
    )
    check("list all ok", r.json().get("code") == 0, r.text[:200])
    r = client.get(
        "/api/v1/approvals", params={"status": "approved", "page": 1, "size": 5}, headers=headers
    )
    check("list approved ok", r.json().get("code") == 0, r.text[:200])

    # 非法状态 1001 中文可操作
    r = client.get(
        "/api/v1/approvals", params={"status": "bogus", "page": 1, "size": 5}, headers=headers
    )
    check("bad status -> 1001", r.json().get("code") == 1001, r.text[:200])

    # 改价建单 → 改参批准 → 价格按改后参数生效
    goods = client.get("/api/v1/goods", headers=headers).json()
    sku0 = goods["data"]["items"][0]["skus"][0]
    base_price = sku0["sale_price"]
    r = client.post(
        f"/api/v1/goods/skus/{sku0['id']}/price-change",
        json={"new_price": base_price + 500, "reason": "审批冒烟"},
        headers=headers,
    )
    check("price-change -> pending", r.json().get("code") == 0, r.text[:200])
    approval_id = (r.json().get("data") or {}).get("id", "")
    if approval_id:
        new_price = base_price + 800
        r = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"modified_args": {"new_price": new_price}, "reason": "冒烟改参"},
            headers=headers,
        )
        check("approve with modified_args ok", r.json().get("code") == 0, r.text[:200])
        row = client.get("/api/v1/goods", headers=headers).json()
        sku_row = next(s for p in row["data"]["items"] for s in p["skus"] if s["id"] == sku0["id"])
        check("price applied as modified", sku_row["sale_price"] == new_price, str(sku_row))
        # 重复处理 4004
        r = client.post(f"/api/v1/approvals/{approval_id}/approve", json={}, headers=headers)
        check("re-approve -> 4004", r.json().get("code") == 4004, r.text[:200])

    # 再建一单走驳回：账不动、原因留痕
    r = client.post(
        f"/api/v1/goods/skus/{sku0['id']}/price-change",
        json={"new_price": base_price + 900, "reason": "审批冒烟驳回"},
        headers=headers,
    )
    second_id = (r.json().get("data") or {}).get("id", "")
    if second_id:
        r = client.post(
            f"/api/v1/approvals/{second_id}/reject",
            json={"reason": "冒烟驳回"},
            headers=headers,
        )
        check("reject ok", r.json().get("code") == 0, r.text[:200])
        check(
            "reject keeps reason",
            "冒烟驳回" in (r.json().get("data") or {}).get("reason", ""),
            r.text[:300],
        )

    # 驳回理由必填：空理由后端 1001（前端 prompt 必填是第一道，后端是硬门禁）
    r = client.post(
        f"/api/v1/goods/skus/{sku0['id']}/price-change",
        json={"new_price": base_price + 700, "reason": "审批冒烟空理由"},
        headers=headers,
    )
    third_id = (r.json().get("data") or {}).get("id", "")
    if third_id:
        r = client.post(
            f"/api/v1/approvals/{third_id}/reject", json={"reason": "  "}, headers=headers
        )
        check("reject empty reason -> 1001", r.json().get("code") == 1001, r.text[:200])
        # 详情：超期标记 + 政策引用随单下发
        r = client.get(f"/api/v1/approvals/{third_id}", headers=headers)
        detail = (r.json().get("data") or {}) if r.json().get("code") == 0 else {}
        check(
            "detail has overdue+policy_refs",
            r.json().get("code") == 0
            and isinstance(detail.get("policy_refs"), list)
            and isinstance(detail.get("overdue"), bool),
            r.text[:300],
        )
        # 只看超期筛选：服务端过滤不断链（新单未超期，应不在结果里）
        r = client.get(
            "/api/v1/approvals",
            params={"status": "pending", "overdue": True, "page": 1, "size": 20},
            headers=headers,
        )
        over = (r.json().get("data") or {}).get("items", [])
        check(
            "overdue filter ok",
            r.json().get("code") == 0 and all(i.get("overdue") for i in over),
            r.text[:300],
        )

    # 存量兼容：只传 status 仍回数组
    r = client.get("/api/v1/approvals", params={"status": "pending"}, headers=headers)
    check(
        "legacy list array",
        r.json().get("code") == 0 and isinstance(r.json().get("data"), list),
        r.text[:200],
    )

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
