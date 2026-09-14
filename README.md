# 多模态智能电商客服系统

> 版本：v0.2.7 | 日期：2026-09-15 | 状态：**P0/P1 代码已落地，CI/CD 与容器化部署已跑通**（文档基线 → 可运行系统）

**多模态交互（文本/图片/语音）+ Agent Runtime 状态机 + 场景化 RAG 与业务连接器 + 人机协同审批与坐席工作台 + 多租户与模型网关 + 全链路可观测与评估 + K8s 云原生交付 + 成本与 ROI 闭环 = 生产可用、可治理、可评估、成本可控的智能客服平台。**

面向电商服装行业（淘宝 / 抖店 / 拼多多 / 京东 / 独立站）的智能客服系统。这些渠道日均咨询 800–1200 条，大促放大 5–10 倍，尺码 / 面料 / 优惠 / 物流 / 退换是高频重复问题，且售后需要传瑕疵图、发语音——传统文本机器人无法闭环，大模型直答幻觉率又不可控。本项目用**多模态 + 强约束 RAG + 人机协同审批**把这套流程做成可生产交付的系统。

---

## 1. 量化目标

| 目标       | 指标                                                                          |
| ---------- | ----------------------------------------------------------------------------- |
| 降本增效   | 自动解决率 ≥ 80%，单会话成本 ≤ 人工的 1/10                                    |
| 多模态闭环 | 文本流式 + 图片瑕疵检测 + 语音转写合成，低置信一律兜底转人工                  |
| 业务精准   | RAG 强约束 + 引用必现 + 无据拒答，幻觉率 ≤ 2%，grounded ≥ 95%                 |
| 生产可控   | 多租户隔离、敏感操作审批 100%、全链路审计、成本归因误差 < 5%、大促可用 99.95% |
| 性能       | 首字 P95 < 2s，完整响应 < 10s，k6 压测 1000 混合并发（文 70 / 图 20 / 音 10） |
| 视觉检测   | 瑕疵分类 F1 ≥ 0.85，召回 ≥ 0.9（200 张/类测试集）                             |
| 灾备       | RTO < 15min，RPO < 5min，回滚 < 5min                                          |

## 2. 范围

**In：** C 端咨询、图文售后、语音客服、订单 / 物流 / 库存 / 优惠 / 退款工具、审批转人工、坐席工作台、运营后台（知识 / Prompt / 评估）、模型网关与可观测、K8s 交付。

**Out（预留接口）：** 实时电话外呼、视频客服、跨境多语言（仅预留 `locale` + 模型路由位）、OCR 吊牌 / 以图搜款（P1）。

---

## 3. 技术选型

| 维度        | 开发默认                                                   | 生产标准                                                                                          |
| ----------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 对话 LLM    | Qwen2.5-7B-Instruct                                        | 模型网关路由：小模型优先，复杂上大模型；支持硅基流动 / OpenAI / 通义 / 私有 vLLM，Fallback 链必填 |
| 视觉 VLM    | Qwen3-VL-8B-Instruct                                       | 同左，GPU 节点池常驻 + 预热；挂了降级人工复核，不硬失败                                           |
| 语音        | SenseVoiceSmall ASR + edge-tts 晓晓                        | 网关封装，可切音色；低置信转文字兜底                                                              |
| RAG 向量    | ChromaDB + BGE-small-zh（CPU）                             | pgvector 起步，> 100 万向量切 Milvus / Qdrant，统一 `RagService` 接口                             |
| 业务 DB     | SQLite 兼容                                                | PostgreSQL 主从 + Alembic 版本迁移                                                                |
| 缓存 / 队列 | Redis 单机                                                 | Redis Cluster/Sentinel + Celery/ARQ + Streams/RabbitMQ，Worker 由 KEDA 按队列长度伸缩             |
| 对象存储    | MinIO                                                      | S3 / OSS / MinIO（统一 S3 协议），瑕疵图人脸打码后存                                              |
| 前端        | Vue3 + TS strict + Element Plus + Pinia + Vite + pnpm      | 同左 + CDN + Nginx                                                                                |
| 后端        | FastAPI + Pydantic v2 + SQLAlchemy 2.0 async               | + Gunicorn/Uvicorn + K8s HPA                                                                      |
| 可观测      | OTel + Prometheus + Grafana + Loki/ELK + Sentry + Langfuse | 同左，日志字段强制带 `trace / tenant / user`                                                      |
| 嵌入式重排  | bge-reranker                                               | 不可用时回退分数排序                                                                              |
| 测试        | pytest / Vitest / Playwright / MSW / k6                    | 同左 + 黄金集评估 + 发布门禁                                                                      |

**工程原则：** API 薄、Service 厚、Runtime 专、工具可插拔、RAG / 记忆 / 网关独立；一切皆代码、不可变镜像、无状态优先、控制面 / 数据面分离、默认安全、可回滚。

---

## 4. 总体架构

```text
渠道层：淘宝 / 抖音 / 拼多多 / 京东 / 独立站 / Web / 工单 / 语音
  ↓
体验层：对话助手 | 任务中心 | 坐席工作台 | Agent 运营后台
  ↓
接入层：API 网关(BFF) | SSO | 多租户隔离 | 限流熔断 | 审计
  ↓
Agent 平台层：Runtime 状态机 | 多模态路由 | 工具注册 | RAG | 记忆
              | 模型网关 | 策略引擎 | 审批 | 评估 | 可观测
  ↓
数据集成层：PostgreSQL | Redis | 向量库 | 对象存储 | MQ | 业务连接器
  ↓
基础设施：K8s | GPU 调度 | CI/CD | OTel / Prom / Loki / Sentry
横切治理：安全合规 | RBAC/ABAC | 审计 | 成本 | SLO
```

**Agent Runtime 状态机：** `IDLE → PLANNING → ACTING → OBSERVING → REFLECTING → DONE`，分支 `WAITING_APPROVAL / WAITING_HUMAN / FAILED`。每步持久化检查点，支持暂停 / 恢复 / 重试 / 超时 + 死信队列，工具调用必经 `policy.check`。

**RAG 在线链路：** Query → 双路召回（向量语义 + 关键词）→ RRF 融合 → bge-reranker 重排 → 治理双阶段过滤（租户 / 密级 / 生效期）→ 多样性裁剪 → 阈值拒答 → 生成 + 引用 + faithfulness。

---

## 5. 文档地图（Single Source of Truth）

| 改什么                       | 先读什么                                                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 需求 / 验收口径              | [`多模态智能电商客服系统需求文档-FRDv2.md`](多模态智能电商客服系统需求文档-FRDv2.md)                                                       |
| 企业级 FRD / 架构分层 / 选型 | [`电商开发文档.md`](电商开发文档.md)、[`后端工程化.md`](后端工程化.md)、[`前端工程化.md`](前端工程化.md)、[`部署工程化.md`](部署工程化.md) |
| 页面 / 组件 / 路由           | [`页面设计.md`](页面设计.md) — §1 路由表、§3 页面详设、§7 组件清单                                                                         |
| 接口 / SSE / 错误码          | [`API接口与SSE事件协议规范.md`](API接口与SSE事件协议规范.md)                                                                               |
| 表 / 键 / 存储               | [`数据模型与存储设计.md`](数据模型与存储设计.md)                                                                                           |
| RAG 链路                     | [`RAG知识库构建检索治理规范.md`](RAG知识库构建检索治理规范.md)                                                                             |
| 测试 / 门禁                  | [`测试评估验收方案.md`](测试评估验收方案.md)                                                                                               |
| 选型变更                     | [`ADR规范与模板.md`](ADR规范与模板.md)                                                                                                     |
| **人 + AI 统一执行入口**     | [`AGENTS.md`](AGENTS.md)                                                                                                                   |

> **口径注意：** `多模态智能电商客服系统需求文档-FRDv2.md` 自述为 **FRD v2.0**，`电商开发文档.md` 自述为 **FRD v3.0**（替代原架构指南版），两者存在版本交叠；`AGENTS.md` §1 目前把「需求 / 验收口径」指向 FRDv2。**落地前需先收敛为唯一基线**，避免 AI 与开发者读到互相冲突的编号（如 FR-1.1 的 SSE 事件形态：FRDv2 用 `source/phase/message/done`，FRD v3 的 `AgentEvent` 仍是旧的 `text/tool_call/tool_result` 写法）。**项目实际形态以 `API接口与SSE事件协议规范.md` §5 为准。**

---

## 6. 目录结构

```text
多模态智能电商客服系统/
├── AGENTS.md                      # 人与 AI 的唯一执行入口（只索引，不复制正文）
├── README.md
│
├── 多模态智能电商客服系统需求文档-FRDv2.md   # 需求 / 验收口径
├── 电商开发文档.md                          # 企业级 FRD v3 + 架构指南
├── 前端工程化.md / 后端工程化.md / 部署工程化.md
├── 页面设计.md / API接口与SSE事件协议规范.md
├── 数据模型与存储设计.md / RAG知识库构建检索治理规范.md
├── 测试评估验收方案.md / ADR规范与模板.md
├── ADR-0001-本地Ollama大模型接入.md / ADR-0002-CI先行与SHA不可变部署.md
│
├── backend/                       # FastAPI（已落地）
│   ├── app/
│   │   ├── api/v1/endpoints/      # auth/chat/sessions/orders/goods/inventory/logistics/
│   │   │                          # reviews/promos/documents/approvals/tasks/tickets/admin/governance
│   │   ├── core/                  # responses/security/rbac/governance/user_context/
│   │   │                          # middleware/observability/exceptions
│   │   ├── db/                    # SQLAlchemy 模型 + seed.py + Alembic 迁移
│   │   └── services/              # 纯业务逻辑；llm_service.py 为模型唯一出口（ADR-0001）
│   ├── tests/                     # pytest 单测/集成 + smoke_*.py 联调脚本
│   ├── requirements.txt           # 依赖清单（已固化）
│   ├── pyproject.toml             # ruff / mypy / pytest / coverage ≥ 70
│   └── Dockerfile                 # 非 root appuser；/srv/app/data 预建并 chown（卷权限坑已修）
│
├── frontend/                      # Vue3 + TS + Element Plus + Pinia（已落地）
│   ├── src/
│   │   ├── api/                   # http.ts dispatch 分发层 + 按域文件 + index.ts barrel
│   │   ├── views/<domain>/        # 14 域：auth/agent/workbench/dashboard/admin/goods/
│   │   │                          # inventory/orders/logistics/marketing/reviews/knowledge/studio/widget
│   │   ├── {components,composables,stores,types}/
│   │   ├── shared/                # v-permission 指令等
│   │   └── mock/                  # 后端不可用时的降级演示数据
│   ├── eslint.config.js / .prettierrc / commitlint.config.cjs / .husky/
│   └── Dockerfile                 # 多阶段：node 构建 → nginx 托管 + /api 同源反代
│
├── docker-compose.yml             # 一键部署：GHCR 镜像 + 命名卷 + 健康检查
├── deploy/
│   ├── deploy.ps1                 # 拉取 + 起栈 + 4 项端到端验证（容器/首页/反代/登录）
│   ├── nginx.conf                 # SPA + SSE 不缓冲（proxy_buffering off）
│   └── argocd/                    # reai-dev.yaml（自动同步）/ reai-prod.yaml（手动审批）
│
├── .github/workflows/
│   ├── ci.yml                     # backend / frontend / security / commitlint / docs-guard
│   ├── package.yml                # push main 构建前后端镜像推 GHCR（latest + 短 sha + tag）
│   ├── cd-update.yml              # package 成功后把镜像版本写回部署仓库（GitOps）
│   └── release.yml                # 版本发布
│
├── scripts/
├── .codebuddy/{rules,skills,memory}/   # AI 约束与工作记忆（随仓库提交）
└── skills/                        # 技能源文件（与 .codebuddy/skills 同步）
```

### Agent Runtime 模块结构（v0.2.6 已落地）

```text
backend/app/modules/agent/         # Agent Runtime 状态机（IDLE→PLANNING→ACTING→OBSERVING→REFLECTING→DONE）
  contracts.py    # 状态机白名单 TRANSITIONS + ToolSpec + JSON Schema 子集校验（无三方依赖，中文报错）
  registry.py     # 工具注册中心（超时/重试口径单源解析）
  policy.py       # Scope 硬拦 + 敏感动作恒判送审
  executor.py     # 30s 超时、幂等退避重试 3 次、非幂等恒 1 次、连续失败熔断 60s、全分支 tool_calls 审计
  connectors.py   # 附录 A 6 个业务连接器（order/logistics/stock/coupon/kb/refund）
  runtime.py      # 规则规划 → 逐步执行 → tasks.checkpoint 每步落盘 → resume 续跑不重放
  bootstrap.py    # 启动幂等注册，失败只告警不阻断
                                   # 对话主链检索段经 runtime.orchestrate() 接线（AGENT_CHAT_ORCHESTRATE 可一键回退直连检索）
```

---

## 7. 快速开始

### 环境要求

| 组件    | 版本                            |
| ------- | ------------------------------- |
| Node.js | 20.11.0（见 `frontend/.nvmrc`） |
| pnpm    | ≥ 9                             |
| Python  | 3.11+                           |

### 一键部署（Docker Compose，推荐）

```powershell
powershell -File deploy/deploy.ps1
# 拉取 GHCR 镜像 → 起栈 → 4 项端到端验证：
#   后端容器健康 / 前端首页(:8080) / Nginx 反代 /api / 登录签发 token
# 访问 http://127.0.0.1:8080   默认账号 admin / admin123
```

镜像由 CI 自动发布（push main 触发 `package.yml`），无需本地构建或 GHCR 凭据。

### 前端

```bash
cd frontend
pnpm install          # 同时会装 husky 钩子
pnpm dev              # Vite 开发服务（:5173，/api 代理到 :8000）
pnpm lint             # ESLint，要求 0 errors
pnpm typecheck        # vue-tsc
pnpm test             # Vitest
pnpm build            # vue-tsc --noEmit && vite build
```

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000             # 端口 8000，与 vite proxy 口径一致
```

开发默认账号 `admin / admin123`（租户 `demo-tenant`，全走 `Settings.SEED_*`，`.env` 可覆盖；启动时自动建 SQLite 并写种子数据）。大模型默认接本地 Ollama `qwen2.5:0.5b`（ADR-0001），不可用时自动降级为模板摘要（仍 200，不返回 500）。

### 常用验证命令

```bash
# 后端
python -m py_compile <改动文件>          # 单文件语法自检
ruff check . ; ruff format --check .
mypy app
pytest --cov=app --cov-report=term-missing
python tests/smoke_x.py [http://127.0.0.1:8000]   # 联调脚本，先起后端（Windows 先 $env:PYTHONUTF8='1'）

# 前端
pnpm lint ; pnpm typecheck ; pnpm build ; pnpm test
```

### 关键配置

模型名、阈值、URL、向量库后端等**全部走 `app/config.py::Settings`（`.env` 可覆盖）并支持热更字段，禁止硬编码**。常用环境变量：

| 变量                                            | 说明                                         |
| ----------------------------------------------- | -------------------------------------------- |
| `HF_ENDPOINT`                                   | 模型下载镜像，加载前 `os.environ.setdefault` |
| `EMB_MODEL` / `BGE_RERANKER`                    | 向量与重排模型                               |
| `TOP_K` / `RRF_K` / `RERANK_TOPN` / `THRESHOLD` | 检索参数（`THRESHOLD` 未达即拒答 2001）      |
| 模型网关相关                                    | 路由、配额、Fallback 链                      |

服务健康与降级状态可查 `GET /governance/status`（向量 / 关键词 / 重排可用性 + 阈值 + 热更字段）。

---

## 8. 核心契约（改代码前必读）

### 统一响应信封

```python
from app.core.responses import ok, fail
return ok({"items": items}, "批量导入任务已提交")
return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
```

前端 `request<T>` 自动解包 `{code, msg, data, trace_id}`，`code !== 0` 抛带 `code` 的 `Error`。

### 错误码号段

| 号段 | 含义       | 常用码                                                                                              |
| ---- | ---------- | --------------------------------------------------------------------------------------------------- |
| 1xxx | 通用       | 1001 参数非法 / 1002 未认证（等同 HTTP 401）/ 1003 无权限 / 1004 不存在 / 1005 配额超限 / 1006 限流 |
| 2xxx | RAG 对话   | 2000 LLM 失败 / 2001 无据拒答 / 2002 会话限流 / 2003 内容不安全 / 2004 图片超限                     |
| 3xxx | 业务 Skill | 3001 订单不存在 / 3002 订单越权 / 3003 退款需审批                                                   |
| 4xxx | 任务       | 4001 任务不存在 / 4002 超时 / 4003 需审批 / 4004 审批驳回                                           |
| 5xxx | 系统       | 5000 内部错误 / 5001 上游失败 / 5002 模型不可用（走降级，绝不向用户返回 500）                       |

### SSE 事件协议

后端事件名固定 **`source / phase / message / done`**（任务类另有 `progress / complete / error`），`done` 载荷必含 `references + guard + faithfulness + trace_id`。请求必须带 `Authorization: Bearer <reai_token>`——**SSE 漏头会导致 401 后本地模拟、服务端无记录**。前端按 `event: / data:` 正则分帧，`done` 的 `JSON.parse` 必须 try/catch。

Nginx / Ingress 必须 `proxy_buffering off; proxy_read_timeout 3600s;`，多副本需粘性会话。

### 安全红线

- **绝不信任请求体里的 `tenant_id` / `user_id` 做权限判断**，可见范围一律由 `governance.access_context()`（从 Token 的 ContextVar 推导）决定，service 层用 `current_user()` 取人。
- 记忆 / 检索读写键必须是 `(tenant, Token 用户名, thread)` 同一口径。
- RAG 检索带 `tenant_id + security_level + 生效期 + 渠道` 过滤；`confidential` 需 `require_perm("kb")`。
- 订单类操作必校验归属，否则返回 `3002`。
- 前端页面 `meta.roles` + 按钮 `v-permission` + 后端 `Depends(get_current_user)` 三重检查；401（含业务码 `1002`）走中央 `handle401()`，禁止各页面自写跳转。
- 密钥绝不进镜像 / 代码 / 前端。

---

## 9. 质量门禁

**可靠性排序：`CI 拦截 > pre-commit hook > ESLint/TS 报错 > always-apply 规则 > Skill > 文档`。**

| 层级     | 机制                                                                                                                                                                          | 位置                         |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| 提交信息 | commitlint（11 种 type + sentence-case + ≤ 100 字符）                                                                                                                         | `frontend/.husky/commit-msg` |
| 提交内容 | lint-staged 自动修复暂存文件                                                                                                                                                  | `frontend/.husky/pre-commit` |
| 前端规范 | ESLint（`func-style: expression` 硬拦 function 声明、`no-restricted-globals` 拦页面直写 fetch）、Prettier、Stylelint（`color-no-hex` 拦硬编码主色）、vue-tsc                  | `frontend/`                  |
| 后端规范 | ruff（`UP` 强制 PEP 604、`ASYNC` 拦 async 里调阻塞库）+ mypy + pytest（覆盖率 `fail_under = 70`）                                                                             | `backend/pyproject.toml`     |
| 流水线   | `ci.yml`：backend（ruff/mypy/pytest）/ frontend（lint/typecheck/test/build）/ security（Trivy）/ commitlint / **docs-guard**（接口↔文档联动硬门禁）；任一红灯不合并           | `.github/workflows/ci.yml`   |
| 发布链路 | `package.yml` push main 自动构建前后端镜像推 GHCR（latest + 短 sha + 版本号）→ `cd-update.yml` 把版本写回部署仓库 → ArgoCD 同步（dev 自动 / prod 手动）；`release.yml` 出版本 | `.github/workflows/`         |

> Windows 上需补 husky 钩子的可执行位：
> `git update-index --chmod=+x frontend/.husky/pre-commit frontend/.husky/commit-msg`

### 测试金字塔

`pytest / vitest → 集成 → smoke_*.py（联调）→ Playwright E2E → k6 压测 → 黄金集评估（≥ 500 条）→ 发布门禁`

Smoke 脚本（`backend/tests/smoke_*.py`）强制风格：头 docstring 写覆盖点与用法、`stdout.reconfigure(encoding="utf-8")`、`httpx.Client(trust_env=False)`、先 `POST /auth/login` 取 token、输出 `PASS/FAIL` 明细 + `RESULT: N passed, M failed`、退出码反映成败。

---

## 10. 面向 AI 协作的约定

本项目同时面向**人与 AI** 开发，因此约束分两层：

**软约束（靠模型自觉）**

- `AGENTS.md`：唯一执行入口，文档索引 + AI 工作流 + 前后端红线。
- `.codebuddy/skills/`：`backend-code-style`、`frontend-code-style`，按需加载完整细则。
- `.codebuddy/rules/`：`alwaysApply` 常驻红线，每轮对话都注入，不依赖语义触发。

**硬约束（机械拦截）**

- 见上一节的质量门禁表。**新增任何「必须遵守」的约定时，优先把它写成可执行的检查，而不是只写进文档。**

**AI 工作流（强制）**

1. 加载对应 Skill，并打开文档地图中对应的一行规范，**不凭记忆写**。
2. 回复开头声明：`对齐文档：<文件名> §<节> + Skill §<节>`。
3. 新文件必须写中文文件头 docstring（职责 + 核心链路 + 对齐章节）。
4. 改接口同步 `API接口与SSE事件协议规范.md` + 自查 `openapi.json`；改 RAG 同步 RAG 规范；改页面同步 `页面设计.md`；改选型先写 ADR。
5. 贴出验证命令的真实输出，不说「应该过了」。
6. 禁止用 `eslint-disable` / `noqa` / `type: ignore` 让门禁变绿。

---

## 11. 前端编码红线（扼要）

- **页面方法一律箭头函数**（`func-style: expression` 硬拦截）：`const loadDocs = async () => {}`，注意箭头函数无提升，先定义后调用。
- 页面**禁止直写 `fetch`**，一律走 `src/api/index.ts`；上传用 `FormData` 且不手设 `Content-Type`；GET 参数一律 `encodeURIComponent`。
- 页面建 `src/views/<domain>/` 下对应目录，逻辑按层放顶层 `src/{components,composables,stores,types}/`，不再建 `features/`。
- Pinia 只用 setup 风格；可复用逻辑抽 `composables/useXxx.ts`，页面只做编排。
- 优先 `AiButton` / `AiInput`；Element Plus 按需引入；样式用设计 token `var(--reai-primary / --reai-card / --reai-text-main / --reai-text-muted / --reai-border / --reai-shadow-*)`，**禁止硬编码主色**。
- 成功 / 失败一律 `ElMessage`；删除 / 停用 / 归档先 `ElMessageBox.confirm`；枚举中文化走映射表。
- 列表页 `onMounted` 调真实接口，`catch` 回退 `@/mock`，保证后端不可用时页面可用；新会话本地先建 `t-${Date.now()}` 占位。
- 跨文件共享的消息形状统一取 `src/types/agent.ts`，禁止各文件自造。

## 12. 后端编码红线（扼要）

- `api/v1/endpoints/*.py` 只做薄封装，业务进 `services/` 且**不 import FastAPI 对象**。
- 成功 `ok()` / 失败 `fail()`，**禁止裸 return dict、禁止 raise HTTPException**；面向用户的 `msg` 必须中文且可操作。
- 类型全注解，PEP 604（`str | None`），**不用 `Optional[]`**。
- 可调参数全进 `Settings`，热更走 `_HOT_FIELDS`；向量 / 关键词走适配层，业务不直连具体库，不可用时自动回退且 `status()` 可见。
- 阻塞 IO（模型推理、文件解析、向量库）必须走 `asyncio.to_thread` 或 `BackgroundTasks`。
- 模型不可用 → 演示流 / 片段摘要降级，**绝不向用户返回 500**。
- 关键链路必埋 `_record() → observability.record()`；审计只追加不改，PII 不存明文，留痕 ≥ 6 个月。

---

## 13. 验收 Checklist（一票否决）

- [ ] 三模态 E2E 打通（文 / 图 / 音）+ 断线重连不丢消息
- [ ] 退款 100% 进审批，越权 0 泄漏，极限词 / PII 过滤生效
- [ ] 引用必现可跳原文，`trace_id` 可复制定位服务端
- [ ] 留痕 ≥ 6 个月可查，成本归因误差 < 5%
- [ ] 灰度 / 蓝绿 / 金丝雀可用，DB 向前兼容，回滚演练 RTO < 15min
- [ ] 黄金集评估达标（自动解决率 ≥ 80%、grounded ≥ 95%、幻觉 ≤ 2%、faithfulness ≥ 0.85），不达标禁发布
- [ ] `pnpm lint` 0 errors + `pnpm typecheck` + `pnpm build` + 关键 vitest + Playwright 冒烟全过

---

## 14. 落地顺序

| 阶段                  | 内容                                                                                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **P0（MVP，4–6 周）** | 后端：Runtime + RAG 闭环 + 统一信封 + 鉴权隔离 + 降级；前端：`/login` `/chat` + 输入三件套 + 引用 + 转人工 + `useAgentStream/useChat/session` + API 唯一入口 + mock 降级 |
| **P1**                | `/workbench` `/approvals` `/tasks` + Trace 专家视图 + 审批改参 + 排队播报                                                                                                |
| **P2**                | `/knowledge` `/studio` `/dashboard` `/admin` `/widget` + 灰度 / 评测 / 归因 + 微前端拆分预留                                                                             |

---

## 15. 贡献与决策

- 提交信息遵循 commitlint：`<type>(<scope>): <subject>`，`type ∈ {feat, fix, docs, style, refactor, perf, test, chore, revert, build, ci}`，`subject` 用 sentence-case 且 ≤ 100 字符。示例：`fix(chat): SSE 请求补齐 Authorization 头`
- 选型变更（模型 / 向量库 / 队列 / 协议 / 鉴权）**先写 ADR 再改代码**：`ADR-000X-*.md`，状态流转 `提议 → 接受/拒绝 → 已落地/已废弃`，模板见 [`ADR规范与模板.md`](ADR规范与模板.md)。
- 联动规则：改路由 / schema / 错误码 → 同 PR 改 API 规范 + `openapi.json` 自查说明；改 RAG 参数 → 同 PR 改 RAG 规范；改表 / 键 / 存储 → 同 PR 改数据模型文档 + Alembic 说明（先加字段后发代码再删旧字段）。
- 操作类协作规范与 AI 工作流见 [`AGENTS.md`](AGENTS.md)。

---

## 16. 当前状态

| 项                                                                                | 状态                                                                                                                                                                                  |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 需求 / 架构 / 接口 / 数据 / 页面 / 测试 文档                                      | ✅ 基线完成（**FRD v2 与 v3 待收敛为唯一基线**）                                                                                                                                      |
| AI 协作层（`AGENTS.md` + skills + alwaysApply rules）                             | ✅ 就绪                                                                                                                                                                               |
| 工程门禁（ESLint / Prettier / Stylelint / ruff / mypy / husky / CI / docs-guard） | ✅ **已对真实代码生效**，CI 绿灯为合并前提                                                                                                                                            |
| `backend/` 应用代码                                                               | ✅ 已落地：鉴权（JWT + 用户切换）、SSE 流式对话 + RAG、订单 / 商品 / 库存 / 物流 / 评价 / 营销 / 文档 / 审批 / 任务 / 工单 / 管理中心，种子数据 + Alembic 迁移，覆盖率门禁 ≥ 70% 达标 |
| `frontend/` 应用代码                                                              | ✅ 已落地：14 个域页面（登录 / 对话 / 坐席工作台 / 管理 / 看板 / 商品 / 库存 / 订单…），`v-permission` 按钮级权限、mock 降级、列表分页规范                                            |
| 容器化部署                                                                        | ✅ 已跑通：compose + GHCR 镜像（CI 自动发布）+ `deploy.ps1` 端到端 4 项验证全绿；v0.1.0 已发布                                                                                        |
| GitOps / K8s                                                                      | 🔶 ArgoCD 清单就绪（`deploy/argocd/`，dev 自动同步 / prod 手动审批），集群侧待接入                                                                                                    |
| Agent Runtime 状态机（`modules/agent/`）                                          | ✅ 已落地（v0.2.6/v0.2.7）：状态机白名单 + checkpoint 断点续跑、工具注册中心、Scope 策略、超时重试熔断执行器、6 连接器、6 条 `/agent/*` 端点；对话主链检索段走 `runtime.orchestrate()`（可一键回退），`refund.create` 恒送审。缺口：编排层「规则机器人」降级话术（FR-5 三级容错第三级） |
| 黄金集（≥ 500 条）与评估流水线                                                    | ⬜ 待建                                                                                                                                                                               |
