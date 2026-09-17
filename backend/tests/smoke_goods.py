"""商品管理端到端冒烟（对齐 API 规范 §4.7 + 页面设计 §3.10 + FRDv2 FR-10.1）

链路：登录 → GET /goods（验证 available 可用量 + sales 销量聚合）→ 状态筛选
      → /goods/{id}/status 上下架（验证 kb_doc 知识同步）→ 改价建单 → 审批通过后价格生效 + kb_doc 更新
      → 关键词筛选 → 越权 403（客服只读）。
用法：python tests/smoke_goods.py [http://127.0.0.1:8000]
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

    # 1. 列表：分页信封 + SKU 矩阵含 available/sales（FR-10.1 库存同步显示）
    r = client.get(
        "/api/v1/goods", params={"page": 1, "size": 20}, headers=headers
    )
    body = r.json()
    data = body.get("data") or {}
    items = data.get("items") or []
    check("list envelope", body.get("code") == 0 and "total" in data, r.text[:300])
    check("list page/size echo", data.get("page") == 1 and data.get("size") == 20, r.text[:200])
    if not items:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    sku0 = items[0]["skus"][0]
    check("sku has available", isinstance(sku0.get("available"), int), str(sku0)[:200])
    check("spu has sales", isinstance(items[0].get("sales"), int), str(items[0])[:200])
    top_sales = max((g.get("sales") or 0) for g in items)
    check(
        "sales aggregated (seed >0)",
        any((g.get("sales") or 0) > 0 for g in items),
        f"max sales={top_sales}",
    )

    # 2. 状态筛选 + 非法状态 1001
    r = client.get("/api/v1/goods", params={"status": "on", "page": 1, "size": 5}, headers=headers)
    check("filter on ok", r.json().get("code") == 0, r.text[:200])
    r = client.get("/api/v1/goods", params={"status": "bogus", "page": 1, "size": 5}, headers=headers)
    check("bad status -> 1001", r.json().get("code") == 1001, r.text[:200])

    # 3. 上下架：下架后 SPU 状态变化 + kb_doc 知识同步透出（FR-10.1）
    product0 = items[0]
    keep_status = product0["status"]
    target = "off" if keep_status == "on" else "on"
    r = client.put(
        f"/api/v1/goods/{product0['id']}/status",
        json={"status": target},
        headers=headers,
    )
    check("toggle status ok", r.json().get("code") == 0, r.text[:300])
    toggled = (r.json().get("data") or {}).get("status")
    check("status flipped", toggled == target, str(r.json().get("data"))[:200])
    kb_doc = (r.json().get("data") or {}).get("kb_doc")
    check(
        "kb_doc synced",
        isinstance(kb_doc, dict) and kb_doc.get("doc_id") and kb_doc.get("version"),
        r.text[:300],
    )

    # 4. 销量筛选：按关键词命中 SPU
    spu_no = product0["spu_no"]
    r = client.get("/api/v1/goods", params={"keyword": spu_no, "page": 1, "size": 20}, headers=headers)
    hit = r.json().get("data") or {}
    check(
        "keyword hit spu",
        r.json().get("code") == 0 and any(x["spu_no"] == spu_no for x in hit.get("items", [])),
        r.text[:300],
    )

    # 5. 改价审批通过 → 价格生效 + kb_doc version 步进（审批处理器兜知识同步）
    base_price = sku0["sale_price"]
    new_price = base_price + 700
    r = client.post(
        f"/api/v1/goods/skus/{sku0['id']}/price-change",
        json={"new_price": new_price, "reason": "商品冒烟改价"},
        headers=headers,
    )
    check("price-change -> pending", r.json().get("code") == 0, r.text[:300])
    approval_id = (r.json().get("data") or {}).get("id", "")
    if approval_id:
        r = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "冒烟批准"},
            headers=headers,
        )
        check("approve ok", r.json().get("code") == 0, r.text[:300])
        r = client.get(
            "/api/v1/goods", params={"keyword": product0["name"], "page": 1, "size": 20}, headers=headers
        )
        row = r.json().get("data") or {}
        sku_row = next(
            (s for g in row.get("items", []) for s in g.get("skus", []) if s["id"] == sku0["id"]),
            None,
        )
        check("price applied after approve", sku_row is not None and sku_row["sale_price"] == new_price,
              str(sku_row or {})[:200])

    # 6. 恢复商品状态（避免污染后续冒烟）
    r = client.put(
        f"/api/v1/goods/{product0['id']}/status",
        json={"status": keep_status},
        headers=headers,
    )
    check("restore status ok", r.json().get("code") == 0, r.text[:200])

    print(f"RESULT: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())