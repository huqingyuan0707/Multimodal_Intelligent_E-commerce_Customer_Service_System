---
description: "让过于夸张的设计更克制｜等价写法 /impeccable quieter [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-quieter，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/quieter.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-quieter $ARGUMENTS

等价于 `/impeccable quieter $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/quieter.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：降强度只降饱和度 / 叠底层 / 动效时长，**不得牺牲信息层级**（状态色 `--reai-success` / `--reai-notice` / `--reai-danger` 的语义映射要保持，枚举标签走 `LEVEL_TAG` 一类映射表）；色值仍只准出现在 `tokens.css`，画板与代码同改。

用户输入：$ARGUMENTS
