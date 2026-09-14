---
description: "Impeccable 设计入口：audit技术检查 | distill去冗余 | clarify改文案 | bolder更大胆 | quieter更克制 | animate加动效"
argument-hint: "audit|distill|clarify|bolder|quieter|animate [target]"
---

<!-- 职责：CodeBuddy 下 /impeccable 统一入口，argument-hint 即输即提示 6 子命令 | 链路：对话框 /impeccable → 本文件 → .github/skills/impeccable/SKILL.md §Commands → reference/<子命令>.md | 对齐：AGENTS.md §2 + SKILL.md §Commands -->

# /impeccable $ARGUMENTS

你是本项目的 Impeccable 设计入口。先按 `.github/skills/impeccable/SKILL.md` §Setup 跑一次 `impeccable context`（Windows 用 `impeccable.cmd`），再按下面路由执行。

## 子命令（输入 `/impeccable` 即弹以下命令列表；两种写法等价）

| 弹窗里的命令 | 等价写法 | 作用 |
|---|---|---|
| `/impeccable-audit` | `/impeccable audit` | 技术质量检查（可访问性、性能、响应式） |
| `/impeccable-distill` | `/impeccable distill` | 去除冗余复杂度 |
| `/impeccable-clarify` | `/impeccable clarify` | 改进不清晰的 UX 文案 |
| `/impeccable-bolder` | `/impeccable bolder` | 让平淡的设计更大胆 |
| `/impeccable-quieter` | `/impeccable quieter` | 让过于夸张的设计更克制 |
| `/impeccable-animate` | `/impeccable animate` | 添加有目的的动效 |

6 个高频子命令各有一份独立注册文件 `.codebuddy/commands/impeccable-<子命令>.md`（对话框输 `/impeccable` 靠前缀匹配弹列表用）；其余 18 个命令仍走本入口，完整表见 `.github/skills/impeccable/SKILL.md` §Commands。


## 路由

- `$ARGUMENTS` 为空：按 `reference/routing.md` §No-argument routing 输出上下文菜单（推荐 2-3 个 + 完整分组菜单），绝不自动执行某个子命令。
- `$ARGUMENTS` 首词是子命令：加载 `.github/skills/impeccable/reference/<子命令>.md` 并照此执行，`[target]` 缺省则用当前改动面。
- 其他设计请求：按 SKILL.md §Routing 当作一般设计任务处理。

用户输入：$ARGUMENTS
