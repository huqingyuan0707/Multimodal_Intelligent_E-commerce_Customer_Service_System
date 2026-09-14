---
description: "让平淡的设计更大胆更有个性｜等价写法 /impeccable bolder [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-bolder，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/bolder.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-bolder $ARGUMENTS

等价于 `/impeccable bolder $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/bolder.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：**大胆只能在既有 token 内做**（`--reai-primary #4f6bff` / `--reai-gold` / `--reai-notice` / 三档 soft 卡底 / 深色底 `#0b1124`），禁止自造色、禁止引入紫色渐变等 AI 套路字体配色；改视觉先改 `design.pen` 画板，画板与代码同 commit（design-guard 拦）。

用户输入：$ARGUMENTS
