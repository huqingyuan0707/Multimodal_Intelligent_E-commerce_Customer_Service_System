---
name: anti-shit-code
description: This skill should be used when implementing, refactoring, or reviewing code in this project to prevent architectural decay ("屎山"). It defines the pre-code design questions, project-specific code-smell signals with their machine gates, the minimum-clean rule, and the pre-merge self-check. Layering red-lines themselves live in AGENTS.md and backend/frontend-code-style — do not duplicate them here.
---

# 防屎山（架构健康 · 提交前自检流程）

> 定位：本 skill **不重复** AGENTS.md / rules 的红线条款，只回答"实现过程中如何让架构不腐烂"。
> 红线唯一出处：`AGENTS.md` §3/§4 + `backend-code-style` / `frontend-code-style`。
> 总原则：**能做成门禁的，绝不只写进文档**（CI 拦截 > pre-commit > lint > 规则 > skill > 散文）。

## 1. 写码前先回答 5 个问题（答不出就停下设计）

1. **这段逻辑属于哪一层？** endpoint / service / store / composable / component 五选一；选不出说明边界还没设计清楚。
2. **这个状态归谁管？** UI 态、业务态、缓存态、权限态不得混在同一对象；跨页面共享必须提升到 store / service / context。
3. **这个函数能否用一句话说清职责？** `doEverything()` / `handleXXX()` / `processData()` 这类泛化命名是屎山早期信号；命名须体现"做什么、属于哪层、与谁交互"。
4. **有没有隐式依赖？** 模块顶层可变全局、隐式 `localStorage`、信任请求体 `tenant_id/user_id` 一律拒绝；上下文只走 `ContextVar` / Token 显式传递。
5. **输入→输出能否被断言？** 断言不出来说明业务边界模糊。API / SSE / 鉴权 / RAG / 审批等关键链路优先补 smoke 或 vitest，而不是"改完手动点一遍"。

## 2. 项目 smell 信号 → 机器门禁对照表

| smell 信号 | 门禁 | 阈值 |
|---|---|---|
| 后端函数圈复杂度过高 | ruff `C901`（`pyproject.toml`） | >15 error |
| 前端函数嵌套过深 | ESLint `max-depth` | >3 error |
| 前端单文件过长 | ESLint `max-lines` | >400 行 error |
| 前端函数参数 / 复杂度溢出 | ESLint `max-params` / `complexity` | >4 / >20 error |
| 后端单文件 >400 行 | `scripts/check_arch.py` | FAIL |
| endpoint 直接触 DB（`execute/add/commit/scalar/select(`） | `scripts/check_arch.py` | FAIL（存量见 §5 基线） |
| views/components 直写 `fetch(` / `axios` | ESLint `no-restricted-globals` + `check_arch.py` 双保险 | FAIL |

运行：`python skills/anti-shit-code/scripts/check_arch.py`（退出码 0 = 过）。
脚本内置棘轮基线：**存量债务记名，新增违规即红；债务减少时提示收紧基线**。

## 3. 量化参考值（超了就拆，不要靠加注释续命）

- 单函数 >60 行或参数 >4 个：优先拆职责；单文件 >400 行：必须拆（前后端门禁已按 400 收口）。
- 嵌套 ≤3 层；`if/elif` 链越拖越长时，先问"是哪个状态/职责没被设计出来"，再动代码。
- 同一行为只允许一个实现：抽象"语义上相同"的业务动作（权限判断、引用列表组装、去重、错误映射），不抽"长得像"的代码。
- 临时修补必须带退出条件：写清 TODO 归属（见 §5 债务清单），否则禁止合入。

## 4. 最小清洁原则（每次改动至少做到一条）

- 修正一处不清晰的命名；或抽出一处重复逻辑；或删除一段死分支；或明确一个模块边界；或补一条真实测试。
- "只加代码不清理上下文" = 让系统在下一次改动时继续腐化。
- AI 协作节奏：一次提交只解决一个根因，不搞混合式大改；需求不清时先定数据流与接口签名再写实现；改动能从提交记录看懂系统演化路径。
- 警惕"为通过测试写特殊分支"：真实可维护的实现通常也更容易测试。

## 5. 已知存量债务（棘轮基线，只准减、不准增）

| 债务 | 数量 | 清偿方式 |
|---|---|---|
| `PLR0913` service 函数参数 >5 | 13 处（approval/goods/inventory/order/promo/review service） | 触碰对应 service 时把参数收进 dataclass / 查询对象，清零后再启用该规则 |
| endpoint 直写 `await db.commit()` | 9 处（logistics/reviews/promos/tickets） | 事务下沉到 service 层 |
| service 依赖 FastAPI 对象 | 未机检 | 后续可扩进 `check_arch.py`（import 扫描） |

## 6. 提交前自检（每项都必须是"是"）

- [ ] §1 五问已回答，改动未破坏 `AGENTS.md` §3/§4 分层红线？
- [ ] 新增状态有唯一所有者，没有新增隐式全局依赖？
- [ ] 没有复制已有实现（同一行为已收口到一处）？
- [ ] `check_arch.py` + `ruff check .` + `pnpm lint` 全绿，且 §5 存量债务未增加？
- [ ] 至少完成一条 §4 最小清洁？
- [ ] 协议 / 文档 / 测试已按 `AGENTS.md` §5 联动规则同步更新？

## 7. 一句话原则

先保边界、再保逻辑；先可测试、再可扩展；能进门禁的，不写进文档。
