"""项目版本三源对齐检查（治「三处打架」：package.json 0.1.0 陈旧、后端硬编码、发版门禁被迫以旧为准）

链路：pre-commit（工作区模式）+ CI version job（同命令，跑在 checkout 上）→ 以
执行步骤.md 头部版本为项目版本唯一口径 → 三源交叉比对。
放行条件：执行步骤头 == frontend/package.json version == backend Settings.APP_VERSION 默认值，
且 backend/app/main.py 必须消费 settings.APP_VERSION（禁止硬编码版本号回潮）。
注意：git tag v0.1.0 是已发布历史，门禁只管当前三源，不追溯 tag。
用法：
  python scripts/check_version.py [--root <仓库根>]
退出码：0=通过，1=ERROR。对齐 AGENTS.md §6「新约定优先写成可执行检查」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="项目版本三源对齐检查")
    parser.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    args = parser.parse_args()
    root = Path(args.root)

    errors: list[str] = []

    plan = read(root, "执行步骤.md")
    # 头部形如「本版日期：2026-09-17（v0.3.12）」（全角括号），兼容半角写法
    m = re.search(r"本版日期：[^\n]*?[\(（]v([^)）]+)[\)）]", plan)
    plan_ver = m.group(1).strip() if m else None
    if not plan_ver:
        errors.append("执行步骤.md 头部取不到版本（期望「本版日期：…（vX.Y.Z）」）")

    try:
        # utf-8-sig：Windows 编辑器可能带 BOM，防误报
        pkg_text = (root / "frontend/package.json").read_text(encoding="utf-8-sig")
        pkg_ver = str(json.loads(pkg_text)["version"])
    except (json.JSONDecodeError, KeyError) as exc:
        errors.append(f"frontend/package.json version 读不到：{exc}")
        pkg_ver = None

    cfg = read(root, "backend/app/config.py")
    m = re.search(r"APP_VERSION:\s*str\s*=\s*\"([^\"]+)\"", cfg)
    app_ver = m.group(1).strip() if m else None
    if not app_ver:
        errors.append("backend/app/config.py 取不到 APP_VERSION 默认值")

    if plan_ver and pkg_ver and pkg_ver != plan_ver:
        errors.append(f"package.json 是 {pkg_ver}，唯一口径（执行步骤头）要求 {plan_ver}")
    if plan_ver and app_ver and app_ver != plan_ver:
        errors.append(f"Settings.APP_VERSION 是 {app_ver}，唯一口径（执行步骤头）要求 {plan_ver}")

    main_py = read(root, "backend/app/main.py")
    if re.search(r"version\s*=\s*\"\d+\.\d+", main_py):
        errors.append("backend/app/main.py 硬编码版本号，请消费 settings.APP_VERSION")

    for msg in errors:
        print(f"[ERROR] {msg}")
    print(f"pins: plan={plan_ver} package={pkg_ver} app={app_ver}")
    print(f"\nRESULT: {'FAIL' if errors else 'PASS'}（ERROR {len(errors)}）")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
