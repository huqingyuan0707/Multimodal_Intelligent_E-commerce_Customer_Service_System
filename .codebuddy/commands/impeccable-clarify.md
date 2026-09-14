---
description: "改进不清晰的 UX 文案（标签、报错、微文案）｜等价写法 /impeccable clarify [target]"
argument-hint: "[target]"
---

<!-- 职责：CodeBuddy 斜杠命令 /impeccable-clarify，让高频子命令在对话框输入 /impeccable 时直接弹列表 | 链路：对话框 → 本文件 → .github/skills/impeccable/reference/clarify.md | 对齐：AGENTS.md §7 + SKILL.md §Commands -->

# /impeccable-clarify $ARGUMENTS

等价于 `/impeccable clarify $ARGUMENTS`。

1. 先取上下文：按 `.github/skills/impeccable/SKILL.md` §Setup 执行 `impeccable context`（Windows 用 `.github/skills/impeccable/scripts/impeccable.cmd`）。
2. 加载并严格照做 `.github/skills/impeccable/reference/clarify.md`。
3. `$ARGUMENTS` 是目标（页面 / 组件 / 流程）；缺省时取当前改动面（`git status --short` + `git diff --stat`）。
4. 本项目附加约束：面向用户的文案一律中文且可操作（说清下一步，别只写「操作失败」）；错误提示要能对上后端 `fail(ErrorCode.*, 中文 msg)` 的信封口径；枚举展示走映射表，禁止模板里散落中文字面量。纯文案改动可不动画板，但提交信息必须带 `Design-Sync: skip reason="仅文案微调"`。

用户输入：$ARGUMENTS
