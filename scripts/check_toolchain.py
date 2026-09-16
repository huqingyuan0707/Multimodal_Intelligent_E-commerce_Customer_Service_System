"""Node 工具链版本对齐检查（治「三处三个版本」：镜像/CI/发版各写各的，构建产物不可复现）

链路：pre-commit（工作区模式）+ CI toolchain job（同命令，跑在 checkout 上）→ 以
frontend/.nvmrc（Node）与 package.json packageManager（pnpm）为唯一源头 → 五源交叉比对。
放行条件：Dockerfile 基座 == .nvmrc；ci/release 的 setup-node == .nvmrc；
ci/release 的 action-setup == packageManager；engines 地板不高于当前钉值。
用法：
  python scripts/check_toolchain.py [--root <仓库根>]
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


def ver(text: str) -> tuple[int, ...]:
    """'22.18.0' → (22, 18, 0)（只取数字节，非数字后缀截断）。"""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def node_of_workflow(text: str) -> str | None:
    """setup-node 的 node-version（首个命中）。"""
    m = re.search(r"node-version:\s*([0-9][0-9A-Za-z.\-]*)", text)
    return m.group(1) if m else None


def pnpm_of_workflow(text: str) -> str | None:
    """pnpm/action-setup 块内 5 行里的 version（防误命中其他 action 的 version）。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "pnpm/action-setup" in line:
            for follow in lines[i + 1 : i + 6]:
                m = re.search(r"version:\s*([0-9][0-9A-Za-z.\-]*)", follow)
                if m:
                    return m.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Node 工具链版本对齐检查")
    parser.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    args = parser.parse_args()
    root = Path(args.root)

    errors: list[str] = []
    node_pin = read(root, "frontend/.nvmrc").strip()
    pkg = json.loads(read(root, "frontend/package.json"))
    pnpm_pin = str(pkg["packageManager"]).split("@", 1)[1]
    docker = re.search(
        r"^FROM node:(\S+) AS builder", read(root, "frontend/Dockerfile"), re.MULTILINE
    )
    docker_ref = docker.group(1) if docker else None
    # 允许 digest 钉死（tag@sha256:…，不可变部署口径）：只比 tag 部分，digest 原样透出备查
    docker_tag = docker_ref.split("@", 1)[0] if docker_ref else None
    ci, release = (
        read(root, ".github/workflows/ci.yml"),
        read(root, ".github/workflows/release.yml"),
    )

    def expect(name: str, actual: str | None, want: str) -> None:
        if actual != want:
            errors.append(f"{name} 是 {actual}，唯一源头要求 {want}")

    if docker_tag != f"{node_pin}-alpine":
        errors.append(
            f"Dockerfile 基座 tag 是 {docker_ref}，唯一源头要求 {node_pin}-alpine"
        )
    expect("ci setup-node", node_of_workflow(ci), node_pin)
    expect("release setup-node", node_of_workflow(release), node_pin)
    expect("ci action-setup", pnpm_of_workflow(ci), pnpm_pin)
    expect("release action-setup", pnpm_of_workflow(release), pnpm_pin)

    engines = pkg.get("engines", {})
    node_floor = re.search(r">=([0-9.]+)", str(engines.get("node", "")))
    if not node_floor or ver(node_floor.group(1)) > ver(node_pin):
        errors.append(
            f"engines.node 地板 {engines.get('node')} 高于当前钉值 {node_pin}"
        )
    if "<" not in str(engines.get("node", "")):
        errors.append("engines.node 缺上限（如 <23），22 系以外大版本会静默放行")
    pnpm_floor = re.search(r">=([0-9.]+)", str(engines.get("pnpm", "")))
    if not pnpm_floor or ver(pnpm_floor.group(1)) > ver(pnpm_pin):
        errors.append(
            f"engines.pnpm 地板 {engines.get('pnpm')} 高于当前钉值 {pnpm_pin}"
        )

    for msg in errors:
        print(f"[ERROR] {msg}")
    print(f"pins: node={node_pin} pnpm={pnpm_pin}")
    print(f"\nRESULT: {'FAIL' if errors else 'PASS'}（ERROR {len(errors)}）")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
