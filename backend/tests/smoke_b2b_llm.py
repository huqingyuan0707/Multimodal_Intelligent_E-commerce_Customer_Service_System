"""B端业务 + 本地大模型端到端冒烟（对齐 API 规范 §4.2/§4.6/§4.7 + ADR-0001）

覆盖：/governance/status 模型巡检 → /chat 出 model/degraded → 种子商品/库存可见
      → 改价进审批→批准生效 → 缺货 3004 走 BusinessError 信封 → 非法状态发货 3005。
用法：python tests/smoke_b2b_llm.py [http://127.0.0.1:8000]
前置：uvicorn 已启动（默认账号 admin/admin123；Ollama 在跑则 model=qwen2.5，否则 degraded=true 仍须 200）。
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
    client = httpx.Client(base_url=BASE, timeout=90.0, trust_env=False)
    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("login ok", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    token = r.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/v1/governance/status", headers=headers)
    llm = r.json()["data"].get("llm", {})
    check("status has llm probe", bool(llm), r.text[:200])
    print(
        f"  llm: available={llm.get('available')} model={llm.get('model')} detail={llm.get('detail')}"
    )

    r = client.post("/api/v1/chat", json={"query": "退货政策是什么"}, headers=headers)
    body = r.json()
    data = body.get("data") or {}
    check("chat 200 envelope", body.get("code") == 0, r.text[:200])
    check("chat exposes model/degraded", "model" in data and "degraded" in data, r.text[:200])
    if data.get("degraded"):
        print("  ⚠ 模型不可达，已降级片段摘要（红线：仍 200 非 500，符合预期）")
    else:
        check(
            "chat model is configured",
            str(data.get("model", "")).startswith("qwen2.5"),
            r.text[:200],
        )
    print(f"  answer: {str(data.get('answer', ''))[:80]}… faithfulness={data.get('faithfulness')}")

    r = client.get("/api/v1/goods", headers=headers)
    goods = r.json()
    check("goods seeded", goods.get("code") == 0 and goods["data"]["total"] >= 1, r.text[:200])

    r = client.get("/api/v1/inventory", params={"only_warn": "true", "size": 200}, headers=headers)
    inv = r.json()
    check(
        "inventory has warning rows",
        inv.get("code") == 0 and any(i["warning"] for i in inv["data"]["items"]),
        r.text[:200],
    )

    # 改价 → 审批 → 批准生效
    sku0 = goods["data"]["items"][0]["skus"][0]
    old = sku0["sale_price"]
    r = client.post(
        f"/api/v1/goods/skus/{sku0['id']}/price-change",
        json={"new_price": old - 100, "reason": "冒烟改价"},
        headers=headers,
    )
    approval = r.json()
    check(
        "price-change -> approval",
        approval.get("code") == 0 and approval["data"]["status"] == "pending",
        r.text[:200],
    )
    if approval.get("code") == 0:
        r = client.post(
            f"/api/v1/approvals/{approval['data']['id']}/approve",
            json={"modified_args": {}, "reason": ""},
            headers=headers,
        )
        check("approve ok", r.json().get("code") == 0, r.text[:200])
        r = client.get("/api/v1/goods", headers=headers)
        row = next(p for p in r.json()["data"]["items"] for s in p["skus"] if s["id"] == sku0["id"])
        sku_row = next(s for s in row["skus"] if s["id"] == sku0["id"])
        check("price applied after approval", sku_row["sale_price"] == old - 100, str(sku_row))

    # 缺货 3004（BusinessError 全局信封）
    wh_id = client.get("/api/v1/inventory/warehouses", headers=headers).json()["data"][0]["id"]
    r = client.post(
        "/api/v1/inventory/moves",
        json={
            "kind": "out",
            "warehouse_id": wh_id,
            "sku_id": sku0["id"],
            "delta": 999999,
            "reason": "冒烟超卖",
        },
        headers=headers,
    )
    check("shortage -> 3004 envelope", r.json().get("code") == 3004, r.text[:200])

    # 非法状态发货 3005
    r = client.get("/api/v1/orders", params={"size": 100}, headers=headers)
    orders = r.json()["data"]["items"]
    check("orders seeded", r.json().get("code") == 0 and orders, r.text[:200])
    bad = next((o for o in orders if "ship" not in o.get("allowed_actions", [])), None)
    if bad:
        r = client.post(
            f"/api/v1/orders/{bad['id']}/ship",
            json={"company": "顺丰", "tracking_no": "SF0000000000"},
            headers=headers,
        )
        check("illegal ship -> 3005", r.json().get("code") == 3005, r.text[:200])
    ok = next((o for o in orders if "ship" in o.get("allowed_actions", [])), None)
    if ok:
        r = client.post(
            f"/api/v1/orders/{ok['id']}/ship",
            json={"company": "顺丰", "tracking_no": "SF9988776655"},
            headers=headers,
        )
        check("legal ship ok", r.json().get("code") == 0, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
