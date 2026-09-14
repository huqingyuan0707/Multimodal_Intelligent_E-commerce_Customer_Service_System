---
description: "添加有目的的动效（微交互、状态过渡）｜等价写法 /impeccable animate [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-animate，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/animate.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-animate $ARGUMENTS

等价于 `/impeccable animate $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/animate.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件 / 交互）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：动效时长与缓动一律取 `tokens.css` 的 `--reai-transition-*` / `--reai-shadow-*` 家族，不散写魔法数字；必须尊重 `prefers-reduced-motion`；不得为动效引入新依赖或改组件结构（结构变了要先改 `design.pen` 画板）。SSE 流式渲染相关动效不得改 `event:/data:` 分帧逻辑与 `done` 的 try/catch。

用户输入：$ARGUMENTS
