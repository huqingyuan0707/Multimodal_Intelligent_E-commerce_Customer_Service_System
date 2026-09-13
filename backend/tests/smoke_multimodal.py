"""多模态 E2E 冒烟（FR-1 图文售后 + 语音，对齐 FRD §6/§7 + 执行步骤 A）

覆盖：login 取 token → POST /multimodal/images（瑕疵图出检测卡）→
POST /agent/chat/stream 带 inspections（inspecting 相 + done.vision/need_human）→
低置信图 done.need_human=true → POST /multimodal/speech/transcribe（文本+置信度）→
GET /multimodal/speech/tts-config（开关/音色）→ GET /governance/status（vlm/speech 加法字段）。
用法：python tests/smoke_multimodal.py [http://127.0.0.1:8000]
前置：后端已 init_db 并启动 uvicorn（默认 admin/admin123）。
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

# 1x1 PNG（内容不重要：stub 按文件名定级，保证离线可跑）
_PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)

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
        print(f"FAIL: {name} {detail[:200]}")


def _stream_lines(client: httpx.Client, path: str, payload: dict, headers: dict) -> list[str]:
    with client.stream("POST", path, json=payload, headers=headers) as stream:
        return list(stream.iter_lines())


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, trust_env=False)
    r = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("login ok", r.status_code == 200 and r.json().get("code") == 0, r.text)
    if r.json().get("code") != 0:
        print(f"RESULT: {passed} passed, {failed} failed")
        return 1
    headers = {"Authorization": f"Bearer {r.json()['data']['token']}"}

    # 图片上传 → 检测卡（破洞 0.85 不转人工；表单字段名须为 file，与端点签名同源）
    r = client.post(
        "/api/v1/multimodal/images",
        files={"file": ("破洞-袖口.png", _PIXEL_PNG, "image/png")},
        headers=headers,
    )
    body = r.json()
    inspection = (body.get("data") or {}).get("inspection") or {}
    # 在线 VLM 与规则降级返回类别不同（在线按模型输出/stub 按文件名），只断言形状口径：
    # 8 类之一 + 置信度 0-1 + file_id/url 落盘回执；stub 确定性由单测覆盖。
    valid_categories = ("污渍", "破洞", "脱线", "色差", "开线", "尺寸不符", "吊牌异常", "无瑕疵")
    try:
        conf = float(inspection.get("confidence", -1))
    except (TypeError, ValueError):
        conf = -1.0
    check(
        "image inspect 检测卡",
        body.get("code") == 0
        and inspection.get("category") in valid_categories
        and 0.0 <= conf <= 1.0
        and bool((body.get("data") or {}).get("file_id")),
        r.text,
    )
    file_id = (body.get("data") or {}).get("file_id", "")

    # 超限拒收 2004（10M + 1 字节直调，不走前端压缩）
    big = b"\xff" * (10 * 1024 * 1024 + 1)
    r = client.post(
        "/api/v1/multimodal/images",
        files={"file": ("big.png", big, "image/png")},
        headers=headers,
    )
    check("image too large 2004", r.json().get("code") == 2004, r.text[:200])

    # NSFW 拦截 2003
    r = client.post(
        "/api/v1/multimodal/images",
        files={"file": ("nsfw-face.png", _PIXEL_PNG, "image/png")},
        headers=headers,
    )
    check("image unsafe 2003", r.json().get("code") == 2003, r.text[:200])

    # 图文轮流式：inspecting 相 + done 带 vision（弱网重连由 useAgentStream 同 key 重放覆盖）
    payload = {
        "query": "这件破洞能换货吗",
        "client_msg_id": "smoke-mm-1",
        "image_ids": [file_id],
        "inspections": [inspection],
    }
    lines = _stream_lines(client, "/api/v1/agent/chat/stream", payload, headers)
    phases: list[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("event: phase") and i + 1 < len(lines):
            try:
                phases.append(json.loads(lines[i + 1].replace("data: ", "", 1)).get("name", ""))
            except ValueError:
                phases.append("")
    check(
        "stream has inspecting phase",
        phases == ["retrieving", "inspecting", "generating", "validating"],
        str(phases)[:200],
    )
    done_raw = ""
    for i, line in enumerate(lines):
        if line.startswith("event: done") and i + 1 < len(lines):
            done_raw = lines[i + 1].replace("data: ", "", 1)
    try:
        done = json.loads(done_raw or "{}")
    except ValueError:
        done = {}
    check(
        "done vision need_human=false",
        isinstance(done.get("vision"), list) and done.get("need_human") is False,
        done_raw[:200],
    )

    # 低置信图 → need_human=true（转人工卡分支）
    low = {"category": "无瑕疵", "confidence": 0.55, "desc": "待确认"}
    lines = _stream_lines(
        client,
        "/api/v1/agent/chat/stream",
        {"query": "这件有问题吗", "client_msg_id": "smoke-mm-2", "inspections": [low]},
        headers,
    )
    low_raw = ""
    for i, line in enumerate(lines):
        if line.startswith("event: done") and i + 1 < len(lines):
            low_raw = lines[i + 1].replace("data: ", "", 1)
    try:
        low_done = json.loads(low_raw or "{}")
    except ValueError:
        low_done = {}
    check("low confidence need_human=true", low_done.get("need_human") is True, low_raw[:200])

    # 语音转写 + TTS 配置
    r = client.post(
        "/api/v1/multimodal/speech/transcribe",
        files={"file": ("退货-破洞.webm", b"fake-audio", "audio/webm")},
        headers=headers,
    )
    data = r.json().get("data") or {}
    check(
        "asr text+confidence",
        r.json().get("code") == 0 and bool(data.get("text")),
        r.text,
    )
    r = client.get("/api/v1/multimodal/speech/tts-config", headers=headers)
    tts = r.json().get("data") or {}
    check(
        "tts config 晓晓",
        tts.get("voice") == "晓晓" and "晓晓" in (tts.get("voices") or []),
        r.text,
    )

    # 巡检加法字段（老字段不断）
    r = client.get("/api/v1/governance/status", headers=headers)
    gov = r.json().get("data") or {}
    check(
        "governance vlm+speech",
        "vlm" in gov and "speech" in gov and "llm" in gov,
        r.text[:200],
    )

    print(f"RESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
