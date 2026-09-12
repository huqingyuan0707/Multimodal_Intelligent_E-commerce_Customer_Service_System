"""文档联动提醒（pre-push 弱提醒，强拦在 CI docs-guard，对齐 AGENTS.md §5）

规则：改后端路由/schema → 应改 API规范；改 RAG → 应改 RAG规范；改页面/路由 → 应改 页面设计；改模型/迁移 → 应改 数据模型。
本脚本只打印提醒，退出码恒 0；CI 同逻辑会 fail。
"""

from __future__ import annotations

import subprocess


def _changed() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "@{push}...HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def main() -> int:
    files = _changed()
    if not files:
        print("SKIP: 取不到 push 差异，仅提醒：改接口/RAG/页面/表结构请同 PR 改对应规范文档。")
        return 0
    rules = [
        ("backend/app/api/", "API接口与SSE事件协议规范.md"),
        ("backend/app/modules/agent/rag/", "RAG知识库构建检索治理规范.md"),
        ("frontend/src/features/", "页面设计.md"),
        ("backend/app/db/", "数据模型与存储设计.md"),
    ]
    warned = False
    for prefix, doc in rules:
        if any(f.startswith(prefix) for f in files) and not any(doc in f for f in files):
            print(f"WARN: 检测到 {prefix} 变更但未见 {doc}，请确认是否需同步。")
            warned = True
    if not warned:
        print("OK: 未发现明显的文档联动缺失。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
