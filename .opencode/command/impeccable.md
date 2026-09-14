<!-- 职责：opencode 下 /impeccable 统一入口，裸调弹菜单、带参路由子命令 | 链路：TUI /impeccable → 本文件 → .github/skills/impeccable/SKILL.md §Commands → reference/<子命令>.md | 对齐：AGENTS.md §2 + SKILL.md §Commands -->
---
description: "Impeccable 设计入口：audit技术检查 | distill去冗余 | clarify改文案 | bolder更大胆 | quieter更克制 | animate加动效"
agent: build
---

# /impeccable $ARGUMENTS

你是本项目的 Impeccable 设计入口。先读 `.github/skills/impeccable/SKILL.md` §Setup 跑一次 `impeccable context`（Windows 用 `impeccable.cmd`），再按下面路由执行。

## 子命令（输入 `/impeccable` 即提示以下列表）

- `audit [target]` — 技术质量检查（可访问性、性能、响应式）
- `distill [target]` — 去除冗余复杂度
- `clarify [target]` — 改进不清晰的 UX 文案
- `bolder [target]` — 让平淡的设计更大胆
- `quieter [target]` — 让过于夸张的设计更克制
- `animate [target]` — 添加有目的的动效

完整 24 命令表见 `.github/skills/impeccable/SKILL.md` §Commands，日常先用上面 6 个。

## 路由

- `$ARGUMENTS` 为空：按 `reference/routing.md` §No-argument routing 输出上下文菜单（推荐 2-3 个 + 完整分组菜单），绝不自动执行某个子命令。
- `$ARGUMENTS` 首词是子命令：加载 `.github/skills/impeccable/reference/<子命令>.md`（如 `audit`→`reference/audit.md`）并照此执行，`[target]` 缺省则用当前改动面。
- 其他设计请求：按 SKILL.md §Routing 当作一般设计任务处理。

用户输入：$ARGUMENTS
