---
name: naming-check
description: This skill should be used when writing, refactoring, or reviewing code in this project to verify naming quality (qualified naming). It defines the naming rules table with its machine gate, the ratchet baseline for legacy debt, and the human-review checklist for semantic naming. Style red-lines themselves live in backend/frontend-code-style and AGENTS.md — do not duplicate them here.
---

# 命名检查（命名质量门禁 · 提交前自检流程）

> 定位：本 skill 回答"命名是否合格怎么判、怎么机检、存量债务怎么管"。
> 命名风格细节唯一出处：`AGENTS.md` §3/§4 + `backend-code-style` / `frontend-code-style`；
> 泛化命名是屎山早期信号的论断出自 `anti-shit-code` §1.3。
> 总原则：**能做成门禁的，绝不只写进文档**——命名检查靠脚本，不靠自觉。

## 1. 机器门禁（每次提交前必跑）

```bash
python skills/naming-check/scripts/check_naming.py   # 退出码 0 = 过
```

脚本扫两类目标（与 `check_arch.py` 同风格：PASS/FAIL + RESULT + 退出码 + 棘轮基线）：

| 规则 | 判定 | 适用范围 |
|---|---|---|
| `py-file-name` | 文件名必须 `snake_case`（`__init__.py` 除外） | `backend/app/**/*.py` |
| `func-name-style` | 函数/方法必须 `snake_case`（dunder 除外） | 同上（AST 解析） |
| `class-name-style` | 类必须 `PascalCase`（`_` 前缀私有类放行） | 同上 |
| `const-name-style` | 模块级赋值禁止 camelCase / 混合大小写下划线（如 `myVar`、`Max_Lines`）；snake 变量、全大写常量、PascalCase 类型别名、dunder、`_` 前缀私有形式均放行 | 同上 |
| `py-generic-name` | 泛化命名黑名单（`foo/bar/temp1/fn1/do_something/process_data/do_everything/my_func` 等） | 同上 |
| `py-single-letter` | 单字母参数仅允许 `_ i j k n x y z a b q`（循环/坐标/数学对偶/查询惯用名） | 同上 |
| `fe-composable-name` | `composables/*.ts` 必须 `useXxx` | `frontend/src/composables/` |
| `fe-vue-name` | 所有 `.vue` 必须 `PascalCase` | `frontend/src/**` |
| `fe-store-name` | `stores/*.ts` 必须 camelCase | `frontend/src/stores/` |
| `fe-generic-name` | `const/let/var/function` 后跟泛化命名黑名单（`temp1/doSomething/handleStuff/processData/myFunc` 等） | `frontend/src/**/*.{ts,vue}` |

## 2. 棘轮基线（存量只准减、不准增）

- 存量违规记在脚本顶部 `BASELINE`（键 `(相对路径, 规则名) -> 允许条数`），**不判红只记数**；
- 任何新增违规立即 FAIL；债务减少时脚本输出"收紧提示"，要求同步调小/删除基线条目；
- 禁止为了过检而盲目扩 `BASELINE` 或黑名单白名单——先判断是不是误报：
  - 确系误报（如 `_UPPER` 私有常量、dunder）→ 修判定逻辑，并写明理由；
  - 确系坏命名 → 改名或按 `(文件, 规则)` 记入 BASELINE，触碰时清偿。

## 3. 已知存量债务（棘轮记名）

| 债务 | 位置 | 清偿方式 |
|---|---|---|
| `const obj` 泛化命名（分页兼容包装） | `frontend/src/api/approvals.ts:10` | 触碰该文件时改名 `rawPage`，清零后删 BASELINE 条目 |

## 4. 机器查不了的：语义命名 5 问（人工评审补充）

脚本只管"形状"合格，"语义"合格靠评审时对照 `anti-shit-code` §1.3：

1. **函数名能否一句话说清职责？** `getData()` / `handleStuff()` 即使全小写也不合格——命名须体现"做什么、属于哪层、与谁交互"。
2. **缩写是否项目内通用？** 项目既有缩写（`rag`/`slo`/`qc`/`kb`）可沿用；自造缩写必须就近有注释或中文 docstring 佐证。
3. **布尔量是否读起来像断言？** TS 变量优先 `is/has/can` 前缀；Python service 查询函数优先 `is_/has_` 或动宾结构。
4. **同一概念是否全链路同名？** 前后端同一实体字段同名（`security_level` 不许前端改名 `level` 各写各的）；枚举值走映射表（如 `LEVEL_TAG`）时映射表键名与后端枚举值严格一致。
5. **新命名是否与领域词汇表一致？** 对话/工单/审批/库存等领域名词以 `数据模型与存储设计.md` 的表/字段名为准，不另造同义词。

## 5. 提交前自检（每项都必须是"是"）

- [ ] `check_naming.py` 通过（退出码 0），且 `BASELINE` 存量未增加？
- [ ] 若本轮修了误报/扩了白名单，判定理由已写进本次提交说明？
- [ ] 新增公开函数/组件/composable 命名能通过 §4 五问？
- [ ] 新文件命名与目录职责匹配（service 落 `services/`、页面方法箭头函数、composable 落 `composables/`）？

## 6. 一句话原则

形状交给脚本，语义交给评审；能进门禁的，不写进文档。
