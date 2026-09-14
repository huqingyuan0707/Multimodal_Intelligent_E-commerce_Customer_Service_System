"""设计先行门禁（对齐 AGENTS.md §5 + .codebuddy/rules/design-first.mdc）

检查四件事：
  1) design.pen 可解析、顶层画板命名 `<中文标题>-/<route>` 且 route 在 页面设计.md §1 路由表内、name 唯一；
  2) 路由覆盖率只升不降（棘轮，基线见下方常量）；
  3) 改了 frontend/src/{views,components,shared/components} 必须同一次改动带上 design.pen，
     或在提交信息里写 `Design-Sync: skip reason="..."` 显式豁免；
  4) 画板色值必须取自 frontend/src/shared/styles/tokens.css（先告警，`--strict-color` 转硬拦）。

用法：
  python scripts/check_design.py                  # 结构 + 覆盖 + 色值（CI 全量）
  python scripts/check_design.py --range A..B     # 追加「UI 与画板同改」检查（CI）
  python scripts/check_design.py --staged         # 追加同改检查（本地 pre-commit）
  python scripts/check_design.py --strict-color   # 色值不一致也判失败
  python scripts/check_design.py --warn-only      # 全部只告警，退出码恒 0（pre-push 弱提醒）
退出码：0 通过（可有 WARN）；1 有 ERROR。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEN = ROOT / "design.pen"
PAGES_DOC = ROOT / "页面设计.md"
TOKENS = ROOT / "frontend" / "src" / "shared" / "styles" / "tokens.css"

NAME_RE = re.compile(r"^(.+)-/([a-z][a-z0-9-]*)$")
ROUTE_ROW_RE = re.compile(r"^\|\s*`(/[a-z][a-z0-9-]*)`")
HEX_FULL_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
HEX_ANY_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGBA_RE = re.compile(r"rgba?\(([^)]+)\)")

# ---- 棘轮基线：只许改善不许恶化；改善后把数字同步调小 ----
LEGACY_UNNAMED_MAX = 0  # 顶层画板无 `<中文标题>-/<route>` 后缀的数量上限（2026-09-14 命名债已清零，收紧到 0）
ROUTE_COVERAGE_MIN = 18  # 已出画板的路由数下限（2026-09-14 §1 路由表 18 条全部出齐 = 满覆盖，再退化即 ERROR）

UI_PREFIXES = (
    "frontend/src/views/",
    "frontend/src/components/",
    "frontend/src/shared/components/",
)
SKIP_TRAILER = "Design-Sync: skip reason="


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def to_rgba(raw) -> tuple[int, int, int, int] | None:
    """把 `#rgb` / `#rrggbb` / `#rrggbbaa` / `rgb(r g b)` / `rgb(r g b / p%)` 统一成 RGBA。"""
    text = str(raw).strip()
    if HEX_FULL_RE.fullmatch(text):
        body = text.lstrip("#").lower()
        if len(body) == 3:
            body = "".join(c * 2 for c in body)
        red, green, blue = (int(body[i : i + 2], 16) for i in (0, 2, 4))
        alpha = int(body[6:8], 16) if len(body) == 8 else 255
        return red, green, blue, alpha
    match = RGBA_RE.fullmatch(text)
    if match:
        values = []
        for part in re.findall(r"[\d.]+%?", match.group(1)):
            if part.endswith("%"):
                values.append(round(float(part[:-1]) * 2.55))
            elif "." in part:
                values.append(round(float(part) * 255))
            else:
                values.append(int(part))
        red, green, blue = (values + [0, 0, 0])[:3]
        return red, green, blue, values[3] if len(values) > 3 else 255
    return None


def norm_color(raw) -> str | None:
    """归一化色值：`#ffffff14` 与 `rgb(255 255 255 / 8%)` 必须判为同一个色。"""
    rgba = to_rgba(raw)
    if rgba is None:
        return None
    red, green, blue, alpha = rgba
    base = f"#{red:02x}{green:02x}{blue:02x}"
    return base if alpha >= 255 else f"{base}@{alpha:02x}"


def colors_in_text(text: str) -> set[str]:
    found = {norm_color(m.group(0)) for m in HEX_ANY_RE.finditer(text)}
    found |= {norm_color(m.group(0)) for m in RGBA_RE.finditer(text)}
    return {c for c in found if c}


def json_break_detail(text: str) -> str:
    """JSON 解析失败时定位最可能的断点：跳过字符串后仍未闭合的容器栈（含行号）。"""
    stack: list[tuple[str, int]] = []
    line = 1
    in_string = False
    escaped = False
    for char in text:
        if char == "\n":
            line += 1
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append((char, line))
        elif char in "]}":
            if stack:
                stack.pop()
    if not stack:
        return ""
    detail = "、".join(f"`{ch}`(第 {ln} 行)" for ch, ln in stack[-5:])
    return f"；未闭合的容器：{detail}"


def routes_from_doc() -> set[str]:
    if not PAGES_DOC.exists():
        return set()
    routes = set()
    for line in PAGES_DOC.read_text(encoding="utf-8").splitlines():
        match = ROUTE_ROW_RE.match(line)
        if match:
            routes.add(match.group(1))
    return routes


def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", "core.quotepath=false", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        return ""


def changed_files(args) -> list[str]:
    cmd = ["diff", "--cached", "--name-only"] if args.staged else ["diff", "--name-only", args.range or ""]
    return [line.strip() for line in git(*cmd).splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", help="git 差异范围，如 origin/main..HEAD")
    parser.add_argument("--staged", action="store_true", help="检查暂存区")
    parser.add_argument("--strict-color", action="store_true", help="色值不一致也判失败")
    parser.add_argument("--warn-only", action="store_true", help="只告警，退出码恒 0")
    args = parser.parse_args()

    errors: list[str] = []
    warns: list[str] = []

    # ---- 1. design.pen 结构 ----
    data = None
    if not PEN.exists():
        errors.append("缺少 design.pen（UI 唯一事实源）")
    else:
        try:
            data = json.loads(PEN.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 解析失败原因需原样回报
            errors.append(f"design.pen 不是合法 JSON：{exc}{json_break_detail(PEN.read_text(encoding='utf-8'))}")
    if isinstance(data, dict) and not data.get("version"):
        errors.append("design.pen 缺少 version 字段")

    top_frames = []
    if isinstance(data, dict):
        top_frames = [c for c in data.get("children", []) if isinstance(c, dict) and c.get("type") == "frame"]
    top_ids = {id(f) for f in top_frames}
    all_frames = [n for n in walk(data) if isinstance(n, dict) and n.get("type") == "frame"]

    routes = routes_from_doc()
    boards: dict[str, str] = {}
    unnamed: list[str] = []
    nested: list[str] = []
    for frame in all_frames:
        name = str(frame.get("name", ""))
        match = NAME_RE.match(name)
        if not match:
            # 命名要求只针对顶层 frame；内部容器 frame 不要求带 route 后缀
            if id(frame) in top_ids:
                unnamed.append(name or "<未命名>")
            continue
        route = "/" + match.group(2)
        if route in boards:
            errors.append(f"画板 route 重复：{route}（{boards[route]} / {name}）")
        boards[route] = name
        if routes and route not in routes:
            errors.append(f"画板「{name}」的 route {route} 不在 页面设计.md §1 路由表内")
        if id(frame) not in top_ids:
            nested.append(name)

    top_names = [str(f.get("name", "")) for f in top_frames]
    duplicated = sorted({n for n in top_names if n and top_names.count(n) > 1})
    if duplicated:
        errors.append("顶层 frame name 重复：" + "、".join(duplicated))
    if nested:
        warns.append(
            f"画板未顶层并列（{len(nested)} 个嵌在其它 frame 内）："
            + "、".join(nested)
            + "；建议提到顶层，一页一 frame"
        )
    if len(unnamed) > LEGACY_UNNAMED_MAX:
        errors.append(
            f"命名不合规的顶层画板 {len(unnamed)} 个（上限 {LEGACY_UNNAMED_MAX}）："
            + "、".join(unnamed)
            + "；应命名为 <中文标题>-/<route>"
        )
    elif unnamed:
        warns.append(f"存量命名债（棘轮 {len(unnamed)}/{LEGACY_UNNAMED_MAX}）：{'、'.join(unnamed)}；改动该画板时补 route 后缀")
    if len(boards) < ROUTE_COVERAGE_MIN:
        errors.append(f"路由覆盖退化：已出画板 {len(boards)} 条 < 基线 {ROUTE_COVERAGE_MIN} 条")
    else:
        missing = sorted(routes - set(boards))
        tail = " ..." if len(missing) > 8 else ""
        print(f"[INFO] 路由覆盖 {len(boards)}/{len(routes) or '?'}；未出画板：{'、'.join(missing[:8])}{tail}")

    # ---- 2. 色值一致性（先告警，可升硬拦） ----
    token_colors = colors_in_text(TOKENS.read_text(encoding="utf-8")) if TOKENS.exists() else set()
    if not token_colors:
        warns.append(f"未读到 token 色值：{TOKENS.relative_to(ROOT)}")
    pen_colors = set()
    for node in walk(data):
        for key in ("fill", "stroke"):
            color = norm_color(node[key]) if key in node else None
            if color:
                pen_colors.add(color)
    off_tokens = sorted(c for c in pen_colors if c not in token_colors)
    if off_tokens:
        detail = "、".join(off_tokens[:12]) + (" ..." if len(off_tokens) > 12 else "")
        message = f"画板 {len(off_tokens)} 个色值不在 tokens.css：{detail}（存量漂移，触碰该画板时一并切到 token）"
        (errors if args.strict_color else warns).append(message)

    # ---- 3. UI 改动与画板同改 ----
    if args.staged or args.range:
        files = changed_files(args)
        ui_files = [f for f in files if f.startswith(UI_PREFIXES)]
        if ui_files and "design.pen" not in files:
            messages = git("log", args.range, "--pretty=%B") if args.range else ""
            if SKIP_TRAILER in messages:
                print(f"[INFO] UI 改动 {len(ui_files)} 个，提交信息含设计同步豁免声明，放行")
            else:
                errors.append(
                    f"改了 {len(ui_files)} 个 UI 文件但未同改 design.pen："
                    + "、".join(ui_files[:5])
                    + f'（微调可在提交信息写 {SKIP_TRAILER}"理由"）'
                )
        elif ui_files:
            print(f"[INFO] UI 改动 {len(ui_files)} 个，已同改 design.pen")

    for warn in warns:
        print(f"[WARN] {warn}")
    for error in errors:
        print(f"[ERROR] {error}")
    print(f"RESULT: {'FAIL' if errors else 'PASS'}（ERROR {len(errors)} / WARN {len(warns)}）")
    if args.warn_only:
        return 0
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
