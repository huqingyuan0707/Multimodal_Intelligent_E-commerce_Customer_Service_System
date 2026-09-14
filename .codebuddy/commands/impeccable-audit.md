---
description: "技术质量检查（可访问性、性能、响应式）｜等价写法 /impeccable audit [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-audit，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/audit.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-audit $ARGUMENTS

等价于 `/impeccable audit $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/audit.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件 / 路由）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：只报问题并给可执行清单，要改视觉必须先回 `design.pen` 画板（design-guard 拦同改）；色值一律 `var(--reai-*)`，禁止硬编码。

用户输入：$ARGUMENTS
