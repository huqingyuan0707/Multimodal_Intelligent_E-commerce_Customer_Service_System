"""提交信息/内容一致性检查（治「顶包」：信息说 A 文件、实际提交 B 文件）

链路：frontend/.husky/commit-msg 钩子（本地）+ CI commitlint job →
      读提交信息 + 文件列表 → 三条规则：
      R1 信息里的驼峰标识符（ToolCallCard/useAgentStream 类）必须能对上文件；
      R2 conventional scope 必须能对上路径（SCOPE_PATHS 映射表）；
      R3 大批量（>15 文件）无正文 → 告警不阻断。
豁免：信息含 trailer `Consistency-Skip: reason="..."` 即放行（同 Design-Sync 口径）。
用法：
  本地（commit-msg 钩子）：python scripts/check_commit_sync.py --msg <文件>
  CI（逐提交）：python scripts/check_commit_sync.py --msg <文件> --files <文件列表>
退出码：0=通过（可含 WARN），1=ERROR。对齐 AGENTS.md §6「新约定优先写成可执行检查」。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# R1：驼峰标识符（≥2 个驼峰节），单大写词（Redis/Workbench）与全大写缩写不参与，避免误伤。
CAMEL_RE = re.compile(
    r"\b([a-z][a-z0-9]*[A-Z][A-Za-z0-9]*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]+)\b"
)
# 技术名词白名单：常出现在信息里但天然没有同名文件，命中即豁免 R1。
STOPWORDS = {
    "openapi",
    "typescript",
    "codebuddy",
    "github",
    "gitlab",
    "jsonschema",
    "sse",
    "vitest",
    "vue",
    "pinia",
    "elementplus",
    "docker",
    "dockerfile",
    "argocd",
    "kibana",
    "prometheus",
    "grafana",
    "chromadb",
    "aiosqlite",
    "sqlalchemy",
    "fastapi",
    "pyproject",
    "commitlint",
    "lint",
    "staged",
    "golden",
    "smoke",
    "e2e",
    "hotfix",
    "revert",
}

# R2：scope → 允许的路径关键字（小写子串匹配完整路径）。空列表=不校验该 scope。
SCOPE_PATHS: dict[str, list[str]] = {
    "workbench": ["workbench"],
    "chat": ["chat"],
    "rag": ["rag", "knowledge"],
    "knowledge": ["knowledge", "rag"],
    "auth": ["auth"],
    "admin": ["admin"],
    "tasks": ["task"],
    "approvals": ["approval"],
    "dashboard": ["dashboard", "screen"],
    "screen": ["screen", "dashboard"],
    "goods": ["goods"],
    "orders": ["order"],
    "inventory": ["inventory"],
    "logistics": ["logistics"],
    "finance": ["finance"],
    "marketing": ["marketing"],
    "purchase": ["purchase"],
    "risk": ["risk"],
    "theme": ["tokens.css", "theme", "fonts.css", "design.pen"],
    "ci": [".github", "workflows", "scripts/"],
    "deploy": ["deploy"],
    "memory": [".codebuddy/memory"],
    "pages": ["页面设计", "design.pen"],
    "handoff": ["handoff"],
    "agent": ["agent"],
    "widget": ["widget"],
    "multimodal": ["multimodal", "vision"],
    "observability": ["observability"],
    "governance": ["governance"],
}

# R3：大批量阈值（超过则要求正文列出要点）
BULK_FILES = 15

SUBJECT_RE = re.compile(r"^(\w+)(?:\(([\w-]+)\))?(!)?:\s")


def staged_files() -> list[str]:
    """读本地暂存区文件清单（core.quotepath=false 防中文路径八进制转义）。"""
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def extract_identifiers(message: str) -> list[str]:
    """R1 素材：信息中的驼峰标识符（去重、去白名单）。"""
    seen: dict[str, None] = {}
    for token in CAMEL_RE.findall(message):
        low = token.lower()
        if low in STOPWORDS or any(s in low for s in STOPWORDS):
            continue
        seen.setdefault(token)
    return list(seen)


def check(message: str, files: list[str]) -> tuple[list[str], list[str]]:
    """纯函数：返回 (errors, warnings)。文件清单为空时跳过文件类规则（无从判起）。"""
    errors: list[str] = []
    warnings: list[str] = []
    if re.search(r"^Consistency-Skip:\s*reason=", message, re.MULTILINE):
        warnings.append("命中 Consistency-Skip 豁免，跳过一致性检查")
        return errors, warnings
    lowered = [f.lower() for f in files]

    # R1 标识符 ↔ 文件
    for token in extract_identifiers(message):
        if not any(token.lower() in path for path in lowered):
            errors.append(f"R1 信息提到「{token}」，但文件清单里没有对应文件（顶包嫌疑）")

    # R2 scope ↔ 路径
    first_line = next((ln for ln in message.splitlines() if ln.strip()), "")
    m = SUBJECT_RE.match(first_line)
    if m and m.group(2):
        scope = m.group(2).lower()
        patterns = SCOPE_PATHS.get(scope)
        if patterns is None:
            warnings.append(f"R2 未知 scope「{scope}」，未校验（可在 SCOPE_PATHS 补映射）")
        elif patterns and not any(p.lower() in path for p in patterns for path in lowered):
            errors.append(
                f"R2 scope({scope}) 期望路径 {patterns}，但 {len(files)} 个文件全不相干"
            )

    # R3 大批量要求正文
    if len(files) > BULK_FILES and len([ln for ln in message.splitlines() if ln.strip()]) < 2:
        warnings.append(f"R3 本次提交 {len(files)} 个文件但无正文，建议列出要点清单")
    return errors, warnings


def read_text_lenient(path: str | Path) -> str:
    """读文本并兼容 PowerShell `>` 重定向产生的 UTF-16 BOM（钩子/CI 场景实测会踩）。"""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="提交信息/内容一致性检查")
    parser.add_argument("--msg", required=True, help="提交信息文件路径（UTF-8）")
    parser.add_argument("--files", help="文件清单路径（每行一个；缺省读 git 暂存区）")
    args = parser.parse_args()

    message = read_text_lenient(args.msg)
    # 剔除注释行（commit 模板）
    message = "\n".join(ln for ln in message.splitlines() if not ln.startswith("#"))
    if message.strip().startswith("Merge "):
        print("合并提交，跳过一致性检查")
        return 0
    if args.files:
        lines = read_text_lenient(args.files).splitlines()
        files = [ln.strip() for ln in lines if ln.strip()]
    else:
        files = staged_files()
    if not files:
        print("文件清单为空，跳过（无可校验内容）")
        return 0

    errors, warnings = check(message, files)
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")
    print(f"\nRESULT: {'FAIL' if errors else 'PASS'}（ERROR {len(errors)} / WARN {len(warnings)}，{len(files)} 个文件）")
    if errors:
        print("确属例外请在提交信息加 trailer：Consistency-Skip: reason=\"理由\"")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
