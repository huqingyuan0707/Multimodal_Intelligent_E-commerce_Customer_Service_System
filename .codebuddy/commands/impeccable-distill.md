---
description: "去除冗余复杂度，把 UI 收敛到本质｜等价写法 /impeccable distill [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-distill，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/distill.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-distill $ARGUMENTS

等价于 `/impeccable distill $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/distill.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件 / 路由）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：删之前先核对状态完整性——空态 / 加载态 / 错误态、`el-pagination`（默认 20）、破坏性操作的 `ElMessageBox.confirm` 二次确认都不许被「简化」掉；视觉结构变动必须先改 `design.pen` 画板再改代码。

用户输入：$ARGUMENTS
