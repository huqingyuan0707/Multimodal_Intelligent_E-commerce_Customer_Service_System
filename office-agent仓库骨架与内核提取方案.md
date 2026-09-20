# office-agent 仓库骨架与内核提取方案

> 版本：v1.0 | 日期：2026-09-19 | 状态：设计定稿（决策记录见 `ADR-0003-办公Agent拆分独立开源项目.md`）
> 定位：开源仓库 office-agent 的初始设计文档；MVP 验收后本文档迁入新仓库 docs/。

## 1. 目标与非目标

- 目标：领域无关的智能办公 Agent 平台——工具注册/审批闸门/长任务调度/审计回放开箱即用，办公场景以插件包形式提供。
- 非目标（MVP 不做）：多租户计费、IM 全量对接（先 webhook 一条）、前端低代码编排、移动端。

## 2. 仓库结构

```
office-agent/
├── LICENSE                        # Apache-2.0
├── README.md / README_EN.md       # 中英双语 + 架构图（五维约束图改造）
├── docker-compose.yml             # SQLite + 演示工具包，五分钟跑通
├── packages/
│   ├── core/                      # Agent 内核（从电商项目提取，见 §3 映射表）
│   ├── server/                    # FastAPI 通用壳：auth/RBAC/tasks/approvals/audit/governance-status
│   ├── tools-office/              # 内置办公工具包（§4）
│   └── mcp-bridge/                # MCP wire 协议桥（FRD §11.6 P2 兑现位）
├── plugins/
│   └── _template/                 # 自定义工具插件模板（SPI 文档配套）
└── apps/web/                      # Vue3 管理台（从电商项目 frontend 抽壳：登录/任务/审批/审计四页）
```

## 3. 内核提取映射表（逐文件，源：backend/app/modules/agent/）

| 源文件 | → 目标包 | 改造点 | 风险 |
|---|---|---|---|
| `contracts.py` | core | 状态机白名单/ToolSpec/Schema 校验**原样迁**；中文报错改 i18n 常量表 | 低 |
| `registry.py` | core | 原样迁；Scope 命名示例改办公域 | 低 |
| `policy.py` | core | Scope 硬拦 + 恒送审原样迁；送审类型枚举改为插件可注册 | 中（接口微调） |
| `executor.py` | core | 超时 30s/退避重试/熔断 60s/全分支审计**原样迁** | 低 |
| `runtime.py` | core | 规划→执行→checkpoint→resume 原样迁；规则规划保留，LLM function-call 规划作为可选 Planner 接口 | 中 |
| `tool_facts.py` | core | 原样迁 | 低 |
| `bootstrap.py` | server | 幂等注册入口改为 app 工厂模式（去电商种子依赖） | 中 |
| `connectors.py` | **不迁主包** | 电商连接器留在本项目，改造为 `plugins/tools-ecommerce`（MCP 化时启动） | — |
| `__init__.py` | core | 公开 API 重导出 | 低 |

配套提取（非 agent 模块）：`db/models_foundation.py` 的 `Task/ApprovalLog/审计表` → server；`core/observability.py` → core；`llm_service.py` 适配层 → core（provider 抽象化，默认 OpenAI 兼容 + Ollama）。

**领域无关化验收**：`grep -riE "finance|purchase|risk|sku|订单|电商" packages/` 仅允许出现在 plugins/tools-ecommerce 与 docs 示例。

## 4. 内置办公工具包（packages/tools-office）

| 层 | 工具 | Scope | 说明 |
|---|---|---|---|
| 读 | `report.generate` / `bi.query` | office:read | 数据源为用户配置的只读 SQL/REST 连接器白名单；**数值一致率 ≥99%**（verify_numbers 后置校验，继承电商项目红线） |
| 读 | `doc.summarize` / `kb.query` | office:read | RAG 内置（vector 适配层沿用，默认 SQLite+内置向量，可切 pgvector） |
| 读 | `schedule.view` | office:read | 日历只读 |
| 写 | `todo.create` / `schedule.book` / `doc.draft` / `ticket.create` / `announce.draft` | office:write | **全部标记需审批**（恒送审）；doc.draft 只起草不发布；幂等键 idem_key 必带 |

## 5. MVP 里程碑

| 期 | 内容 | 验收 |
|---|---|---|
| M0（1 周） | 骨架 + 内核提取 + 测试移植全绿 | py_compile/ruff/pytest 过；grep 领域无关性 PASS |
| M1（2 周） | server 壳 + tools-office 读层 + docker compose demo | 五分钟跑通报表生成；LLM 挂走纯数字模板降级 |
| M2（2 周） | 审批闸门 + 写层工具 + web 四页 | 巡检→建单→审批 E2E；引导词 0 命中 |
| M3 | mcp-bridge + tools-ecommerce 首个外部插件 + SPI 文档 | 电商项目经 MCP 注册成功消费 |

## 6. 开源工程项

- Apache-2.0；零硬编码（Settings/.env 模式平迁）；中英 README；CONTRIBUTING + 行为准则；
- CI：pytest + ruff + 领域无关性 grep 门禁；发布走 PyPI（packages 各自可独立 pip 安装）；
- 安全：SECURITY.md + 密钥仅走环境变量；演示数据内置无 PII。

---

## 7. 两仓库串联与数据交互

### 7.1 总纲：星型拓扑 + 数据不出域

```
┌──────────────────────┐    ① MCP wire / HTTP + JWT     ┌──────────────────────┐
│  office-agent        │ ◄────────────────────────────► │  tools-ecommerce     │
│  （独立开源仓库）      │   ToolSpec 工具调用 + 结果回流   │  （MCP Server 薄壳，  │
│                      │                                │    挂在电商项目内）    │
│  自有库：tasks/审批/   │                                └──────────┬───────────┘
│  办公域数据           │                                           │ 进程内调用
└──────────────────────┘                                ┌──────────▼───────────┐
                                                        │ 电商后端 services      │
                                                        │ （口径钉死层，数据不出域）│
                                                        └──────────────────────┘
```

核心纪律：**office-agent 永不直连电商数据库**。所有数据交互经 tools-ecommerce 暴露的白名单工具——财务差异公式、settled 语义、审批口径等「唯一出处」全在电商 service 层，跨库复制必然制造第二真相源（ADR-0003 否掉方案 A 的理由之一，串联设计延续同一原则）。

### 7.2 数据交互四模式（分阶段启用）

| 模式 | 方向 | 机制 | 场景 | 启用期 |
|---|---|---|---|---|
| ① 拉取 pull | office → 电商 | 工具调用返回 JSON，**必带 `source_endpoint + fetched_at` 溯源** | 日报聚合、审批预审卡、ChatBI | M1 |
| ② 回流 push | office → 电商 | 写动作过 office 审批闸门 → 批准后调电商写接口；**幂等键透传**（office `idem_key` → 电商幂等回放）防重复建单 | 巡检转工单、待办同步 | M2 |
| ③ 事件订阅 | 电商 → office | webhook（SLA 逾期/订单完成触发 office 任务） | 事件驱动自动化 | 远期 |
| ④ 只读副本 | 电商 → office | 定时 ETL 同步到 office 自有库 | 大规模 BI/历史分析 | 按需 |

模式 ①② 为主线：溯源信息是「数值一致率 ≥99%」红线的校验依据；幂等键透传保证「审批批准 + 接口重试」不产生双单。模式 ③④ 起步不做（YAGNI）。

### 7.3 身份与信任

1. **服务账号**：电商项目注册 `svc-office-agent`（复用现有 RBAC，授最小只读权限集 + 指定写权限），不新造权限体系——office-agent 对电商就是一个普通登录用户；
2. **身份透传**：office-agent 调电商 API 带 `X-On-Behalf-Of: <真实用户>`，电商审计记「工具动作实际发起人」——审批留痕不因跨系统而断；
3. **trace_id 贯穿**：office 的 trace_id 作为参数传入电商，电商 observability 原样记录——跨系统排障一条线；
4. **凭据**：双向只走环境变量/secret，绝不入库（两边既有红线）。

### 7.4 三阶段演进（对应里程碑）

- **M0-M1（零串联期）**：两仓库完全独立，office-agent 跑自有演示数据；唯一「串联」是内核同步（先落电商再移植的既定纪律）；
- **M2（HTTP 桥接）**：电商项目把现有 6 连接器 + 查询 service 包成 tools-ecommerce v1，**每个工具 = 调一次电商 REST API（带 JWT）**——不需要真 MCP 协议，docker compose 同网络直调；
- **M3（MCP 标准化）**：tools-ecommerce 升级为标准 MCP Server，office-agent 经 mcp-bridge 接入。ToolSpec 与 MCP tool 定义天然同构（JSON Schema + 名称 + 描述），即 FRD §11.6「P2 只迁协议栈，接口形态不变」——换协议不改业务代码。

### 7.5 可选插件红线

串联是**可选项不是硬依赖**：开源出去的 office-agent 大部分用户没有电商项目——tools-ecommerce 对 office-agent 只是普通插件包，office-agent 对电商项目只是可选增强组件，**两边没有对方都能独立活**。严禁 office-agent 主包出现任何「if 电商」分支，严禁电商项目 import office-agent 任何模块。
