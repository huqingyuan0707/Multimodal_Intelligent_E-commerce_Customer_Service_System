# 企业级大模型驱动电商服装多模态智能客服系统 功能需求文档 FRD v2

> 版本：v2.0 | 日期：2026-09-12 | 状态：基线
> 合并来源：多模态智能电商客服系统需求文档.md / 电商开发文档.md / 前端工程化.md / 后端工程化.md / 部署工程化.md
> 定位：立项 / 招投标 / 研发 / 测试验收统一依据。v1 偏 Agent 技术平台，v2 补齐服装业务深度 + 企业治理 + 量化验收。

一句话定义：**多模态交互（文本/图片/语音）+ Agent Runtime 状态机 + 场景化 RAG 与业务连接器 + 人机协同审批与坐席工作台 + 多租户与模型网关 + 全链路可观测与评估 + K8s 云原生交付 + 成本与 ROI 闭环 = 生产可用、可治理、可评估、成本可控的智能客服平台。**

---

## 1. 文档概述

### 1.1 项目背景
电商服装（淘宝 / 抖店 / 拼多多 / 京东 / 独立站）日均咨询 800-1200 条，高峰 5-10 倍。痛点：人工成本高、响应慢、尺码 / 面料 / 优惠 / 物流 / 退换高频重复；售后需传瑕疵图、发语音，传统文本机器人无法闭环；大模型直答幻觉率高，不可直接生产。

### 1.2 产品目标
1. 降本增效：自动解决率 ≥80%，单会话成本 ≤ 人工 1/10。
2. 多模态闭环：文本流式 + 图片瑕疵检测 + 语音转写合成，置信度兜底。
3. 业务精准：RAG 强约束 + 引用必现 + 无据拒答，幻觉率 ≤2%。
4. 生产可控：多租户隔离、人机协同、审批 100%、全链路审计、成本归因、灰度回滚、大促可用。

### 1.3 范围
In：C 端咨询、图文售后、语音客服、订单/物流/库存/优惠/会员/退款工具、审批转人工、坐席工作台、运营后台、网关/可观测/评估、K8s 交付。
Out（v1 不做，预留接口）：实时电话外呼、视频客服、跨境多语言（仅预留 locale + 模型路由位）。

### 1.4 目标用户
买家 / 人工客服 / 运营 / 平台管理员 / 平台 SRE / 安全合规。

---

## 2. 术语与技术选型基线（统一五篇冲突点）

| 维度 | 开发默认 | 生产标准 | 说明 |
|---|---|---|---|
| 对话 LLM | Qwen2.5-7B-Instruct | 模型网关路由：小模型优先，复杂上大模型；支持硅基流动 / OpenAI / 通义 / 私有 vLLM | 按租户配额 + 成本策略路由，Fallback 链必填 |
| 视觉 VLM | Qwen3-VL-8B-Instruct | 同左，GPU 节点池常驻 + 预热 | 挂了降级为人工复核，不硬失败 |
| 语音 | SenseVoiceSmall ASR + edge-tts 晓晓 | 网关封装，可切音色 | 方言/低置信转文字兜底 |
| RAG 向量 | ChromaDB + BGE-small-zh（CPU） | pgvector 起步，>100 万向量切 Milvus / Qdrant | 统一 `RagService` 接口，底层可换 |
| 业务 DB | SQLite 兼容 | PostgreSQL 主从 + Alembic 版本迁移 | 生产强制 PG |
| 缓存/队列 | Redis 单机 | Redis Cluster/Sentinel + Celery/ARQ + Redis Streams / RabbitMQ | Worker 用 KEDA 按队列长度伸缩 |
| 对象存储 | MinIO | S3 / OSS / MinIO（统一 S3 协议） | 存瑕疵图 / 语音，人脸打码后存 |
| 前端 | Vue3 + TS strict + Element Plus + Pinia + Vite + pnpm | 同左 + CDN + Nginx | 按业务域分层，统一 AgentEvent 协议 |
| 后端 | FastAPI + Pydantic v2 + SQLAlchemy 2.0 async | + Gunicorn/Uvicorn + K8s HPA | Router 薄 / Service 厚 / Runtime 专 |
| 可观测 | OTel + Prometheus + Grafana + Loki/ELK + Sentry + Langfuse | 同左 | 日志字段强制 trace/tenant/user |

工程原则：API 薄、Service 厚、Runtime 专、工具可插拔、RAG/记忆/网关独立；一切皆代码、不可变镜像、无状态优先、控制面/数据面分离、默认安全、可回滚。

---

## 3. 角色与权限矩阵 RBAC/ABAC

| 角色 | 核心权限 | 数据范围 |
|---|---|---|
| 买家 | 发起会话、传图、发语音、看回复 | 仅 `user_id` 本人会话 |
| 人工客服 | 接管/抢接/转接、快捷回复、内部备注、审批敏感操作、改参重试、看完整 Trace | 所属 `tenant_id` + 技能组（售前/售后/VIP） |
| 运营 | 知识 CRUD/版本/检索测试、Prompt 版本灰度、评估集、敏感词/极限词库、大促话术开关 | 所属租户知识库与配置 |
| 管理员 | 租户/订阅/配额/网关/计费/SLO/审计 | 全局，操作留痕 |
| SRE/安全 | 发布/回滚/告警/密钥/网络策略 | 基础设施面 |

强制（与代码 skills 对齐，安全红线）：
- 绝不信任请求体里的 `tenant_id/user_id` 做权限判断，可见范围一律 `governance.access_context()`（从 Token 的 ContextVar 推导）；service 层用 `current_user()` 取人；记忆/检索读写键必须是 `(tenant, Token用户名, thread)` 同一口径。
- RAG 检索带 `tenant_id + security_level + 生效期 + 渠道` 过滤。
- 工具按 Scope 鉴权 `order:read / trade:refund / kb:write` 等；敏感端点 `Depends(require_perm(...))`。
- 前端按钮级 `v-permission` + 路由 `meta.roles` + 后端 `Depends(get_current_user)` 双检；401（含业务码 1002）走中央 `handle401()`。
- 统一信封 `ok(data,msg)/fail(ErrorCode,中文msg,http)`，错误码 1xxx通用/2xxx对话（含2001拒答/2002限流）/3xxx业务/4xxx任务/5xxx系统；`trace_id` 框架自动带。
- 详见 `API接口与SSE事件协议规范.md`、`数据模型与存储设计.md`、`RAG知识库构建检索治理规范.md`、`测试评估验收方案.md`。

---

## 4. 功能需求

### FR-1 多模态智能交互

**FR-1.1 文本客服**
- 多轮对话，意图识别：咨询 / 导购 / 投诉 / 售后；情绪识别：正常 / 不满 / 愤怒。
- RAG 检索后生成，System Prompt 强制“仅基于引用回答”。
- SSE 流式（项目实际形态，详见 API 规范 §5）：事件名固定 `source / phase / message / done`（任务类另有 `progress/complete/error`），`done` 载荷必含 `references + guard + faithfulness + trace_id`；前端按 `event: / data:` 分帧解析，`done` 的 `JSON.parse` 必须 try/catch；请求必须带 `Authorization: Bearer reai_token`。
- 断线重连 + 事件 ID 幂等，前端增量渲染 + 虚拟列表（长会话），乐观更新；新会话本地先建 `t-${Date.now()}`，成功后以后端为准；后端不可用回退 `@/mock` 演示，模型不可用走演示降级绝不 500。

**FR-1.2 图文客服（VLM 瑕疵检测）**
- 限制：≤9 张 / 单张 ≤10M / JPG-PNG-WEBP；超限前端压缩 + 后端拒收码 `IMAGE_TOO_LARGE`。
- 预处理：BGR→RGB，Base64/S3 URL 双入参；必经 NSFW / 黄赌毒 / 人脸检测，人脸打码后存。
- VLM 输出结构化：`{category: 污渍/破洞/脱线/色差/开线/尺寸不符/吊牌异常/无瑕疵, confidence:0-1, bbox?, desc}`。
- 置信度 `<0.6` 或 `无瑕疵但用户坚持` → 自动转人工复核，不硬答。
- 检测结果拼入 LLM 上下文 + RAG 退换政策，生成 `致歉 + 定级 + 方案{退/换/补/修} + 时效`。
- 前端：图片预览 / 缩放 / 标注（可选）/ 检测卡片 + CitationList。
- 预留：OCR（吊牌/面单）、以图搜款找同款。

**FR-1.3 语音客服（ASR/TTS）**
- ≤60s / ≤5M，Mp3/Wav/M4A/Opus；ASR 返回 `text + confidence`，低置信回问确认。
- 回复支持 TTS，可开关、可切音色（默认晓晓），前端波形 + 播放 + 文字对照。
- 录音/转写需明示并获同意；方言/噪音不支持时降级文字并告知。

**FR-1.4 会话管理**
- `session_id` 隔离，PG 持久化 + Redis 短期上下文。
- 双重修剪：轮数 N（默认 20）+ Token 预算 M（默认 8k），超限摘要压缩 + 正则清洗。
- 支持恢复、翻页、按单号关联多会话。

### FR-2 服装业务场景（v1 与 v2 差异最大处）

**售前导购**
- 尺码推荐必填：身高 / 体重 / 三围（可选）/ 版型偏好（修身/常规/宽松）/ 面料弹力；缺参追问，给范围不给绝对值，不确定时给 `M-L 均可，建议 M` + 要更多数据。
- 面料解答、洗护、库存查询、优惠叠加规则引擎（满减/券/预售尾款），大促话术版本一键切换。

**售中**
- 订单查询、物流追踪（节点卡片）、改地址、催发货；调用业务连接器，敏感字段脱敏显示 `138****1234`。

**售后**
- 退换政策咨询、图文瑕疵定级、投诉。7 天无理由 / 质量问题 15 天等按知识生效期判断，过期知识不可召回。
- 主动营销禁令：仅用户触发可推优惠，不主动骚扰。

闭环：发起 → 意图+情绪路由 → RAG+工具 → 回复/转人工 → 持久化 → mining 进运营后台。

### FR-3 Agent Runtime 状态机
`IDLE → PLANNING → ACTING → OBSERVING → REFLECTING → DONE`，分支 `WAITING_APPROVAL / WAITING_HUMAN / FAILED`。
- 检查点每步持久化 `tasks` 表，支持暂停/恢复/重试/超时 + 死信队列。
- 每步 TraceID，工具必经策略引擎 `policy.check`。
- 长任务转异步 + 轮询 / WebSocket，不阻塞 SSE（>30s 自动转异步）。

### FR-4 RAG 知识库与记忆
- 知识格式 JSON：`{title, content, tenant_id, 适用渠道, 生效起止, 版本}`，按业务主题切分，非固定段长。
- 混合检索：向量 + BM25 + rerank，TopK=5，`tenant_id + 生效期` 过滤，热点缓存。
- 无依据拒答话术：“这个问题我暂时没查到权威政策，已为你转人工…”，禁编造单号/政策。
- 前端必显引用来源，可点跳原文。
- 更新走异步 reindex，版本可回滚，运营可检索测试预览。
- 记忆：短期 Redis TTL 24h；长期偏好 PG/向量，需授权，可一键遗忘（GDPR/个保）。

### FR-5 工具调用系统（清单见附录 A）
- 注册中心：JSON Schema + Scope + 幂等键 + 超时 30s 重试 3 次 + 熔断 + 沙箱 + 全审计。
- 三级容错：重试 → 降级预设话术“系统繁忙，已记录，转人工跟进” → 网关熔断切规则机器人。
- 工具调用前端以 ToolCallCard 透明展示，可展开参果。

### FR-6 模型网关与成本
- 统一入口：路由 / Fallback / 缓存 / 限流 / 配额 / Token+GPU 成本归因（按租户/部门/Agent）。
- 小模型优先，复杂升级；Key 集中 Vault / K8s Secret / External Secrets，不进代码/镜像/前端。
- 超预算自动限流或降级 + 告警。

### FR-7 人机协同、审批与坐席工作台

**触发转人工：** 用户喊人工 / 连续 3 次不懂 / 愤怒 / VLM 低置信 / 敏感退款 / 模型连续失败 / 无据拒答。
**坐席工作台（v1 必须有最小闭环）：**
- 待接队列 + 技能组 + 负载均衡 + VIP 优先 + 排队位播报。
- 完整 Trace：规划 / 检索引用 / 工具参果 / Token 耗。
- 快捷回复、内部备注（买家不可见）、抢接/转接、质检打分、绩效统计。
**审批：**
- 退款/补偿/改价进 `WAITING_APPROVAL`，`POST /approvals/{id}/approve|reject`，可改参重试。
- 超时升级、批量审批、移动审批（预留），记录不可篡改、可审计回溯。

### FR-8 运营与管理后台
- 租户与订阅计费：按会话 / 按 Token / 包年，试用 / 欠费停服 / 超额限流。
- Prompt 版本管理 + 灰度 + 回滚；评估集管理；敏感词 + 广告极限词（最/第一/顶级）动态库。
- 大促开关、公告、OpenAPI/Webhook、企微/钉钉告警。
- 前端模块：ChatView / TaskCenter / ApprovalCenter / AgentStudio（Prompt/工具/知识画布）/ AdminPanel（租户/配额/审计）。

### FR-9 可观测与评估
- 日志结构化 JSON：`timestamp/level/service/trace_id/request_id/tenant_id/user_id`，进 Loki/ELK；审计日志单独不可篡改存。
- 指标 Prometheus+Grafana：QPS、首字延迟 P50/P95、错误率、自动解决率、幻觉率、工具成功率、Token/成本、任务完成率、队列长、GPU 利用。
- 追踪 OTel + Langfuse/LangSmith：规划/检索/模型/工具每步。
- 前端 Sentry + Web Vitals LCP/FID/CLS + 埋点。
- 评估：黄金集 ≥500 条（售前 200/售中 100/售后 200 含图文 100），LLM-as-judge + 人工抽检双轨；影子流量 / A-B；不达标禁发布。

---

## 5. 非功能需求 NFR

**性能与 SLO：** 流式首字 <2s（P95），完整 <10s；坐席消息 <1s；1000 并发混合（文 70%/图 20%/音 10%）通过；SSE 关闭缓冲 `proxy_buffering off`，`proxy_read_timeout 3600s`，多副本粘性会话或共享状态。
**可用与灾备：** 日常 99.9%，大促 99.95%，多可用区 + PDB + 优雅停机；DB 每日全量 + WAL，Redis 持久化 + 哨兵/集群，对象存储跨区复制；模型多副本，公有云 Fallback；RTO<15min RPO<5min，定期故障演练。
**安全合规：** 等保 / PIPL / GDPR / 电商法留痕 ≥6 个月；PII 脱敏，不存明文手机地址；Prompt 注入/越狱/图片对抗过滤；WAF + 限流防重放防刷；镜像 Trivy/Grype 扫描 + Cosign 签名 + SBOM；K8s RBAC 最小 + NetworkPolicy 默认拒绝 + Falco/Tetragon 运行时；密钥 Vault/External Secrets。
**工程化：** 后端 Ruff + mypy + pytest + coverage 门禁；前端 ESLint + Prettier + Stylelint + Husky + commitlint + vue-tsc；CI `lint→typecheck→test→build→镜像扫描→SBOM`，不通过不合并；GitOps ArgoCD，滚动/蓝绿/金丝雀/功能开关/影子，DB 迁移先加字段后发代码再删旧字段，向前兼容可回滚。
**成本：** requests/limits 必填，HPA/KEDA 按 CPU/QPS/队列伸缩，GPU 节点池按需启停 + 预热，检索/模型双缓存，月度 ROI 报表 + 预算告警。

---

## 6. 核心业务流程

**P1 图文售后（主流程）：**
1. 买家传图 + “衣服这里破了，怎么处理？”
2. 前端打包 → 网关鉴权 → 对象存储 → NSFW/PII 预检。
3. VLM 检测 `袖口脱线约2cm 0.82`。
4. 拼接检测 + RAG 检索退换政策 TopK。
5. LLM 生成致歉 + 方案 + 引用 → SSE 流式 → 追问是否代申请退货。
6. 确认 → 退款工具 → WAITING_APPROVAL → 坐席批 → 执行 → 审计 → 归档 → mining。
**P2 转人工：** 3 次不懂/愤怒 → WAITING_HUMAN → 坐席看 Trace 接管 → 内部备注 + 质检。

---

## 7. 验收标准（可测口径）

| 项 | 阈值 | 测法 |
|---|---|---|
| 三模态闭环 | 文/图/音全通 | E2E Playwright + MSW mock SSE |
| 自动解决率 | ≥80% | 黄金集 + 线上抽 1000 条人工标，口径：一次解决无需转人工 |
| RAG grounded / 幻觉 | ≥95% / ≤2% | judge + 人工，引用可点溯 |
| 瑕疵分类 F1 / 召回 | ≥0.85 / ≥0.9 | 200 张/类测试集 |
| 敏感操作审批率 | 100% | 审计扫漏 + 渗透越权测 |
| 首字 P95 / 可用 / 转人工接起 | <2s / 99.9% / ≥95% 30s 内 | 压测 + APM |
| 并发 | 1000 混合 | k6/Locust，Ingress 已关缓冲 |
| CI/回滚/灰度 | 全过，一键回滚 <5min | 演示 |
| 成本归因误差 | <5%，单会话 ≤人工 1/10 | 账单对账 |

---

## 8. 分期路线

**P0 MVP 4-6 周：** 文本 + 单图售后 + ASR/TTS 基线 + RAG + 退款审批 + 转人工最小台 + 多租户 + 网关 + SSE + PG/Redis/MinIO + K8s + 可观测 + 黄金集 200 条 + CI 门禁。
**P1 2-4 周：** 以图搜款/OCR/坐席完整台/计费/混合检索 rerank/大促预案/A-B/影子。
**P2 持续：** 多语言/视频/挖掘闭环/微前端拆分 Chat/Studio/Admin/等保认证/灾备演练常态化。

---

## 9. 交付物
前端源码（对话/审批/任务/Studio/Admin）/ 后端（Runtime/RAG/网关/工具/记忆/审批/评估）/ K8s YAML + Dockerfile + Nginx + ArgoCD / API Swagger + 事件协议 doc / 部署运维手册 / pytest+vitest+E2E + 黄金集 + 压测报告 / SBOM + 扫描报告。

## 10. Top 风险
供应商挂 → Fallback + 规则机器人；幻觉赔付 → 引用强制 + 拒答；图片误判 → 阈值 + 人工复核；大促击穿 → 限流 + 预热 + 降级；跨租户串数 → 三重校验 + 渗透测；密钥泄漏 → Vault + 轮换。

---

## 附录 A：业务连接器 API 契约（v1 必实现 7 个）

通用：鉴权 `Bearer JWT(tenant/user/roles)`；幂等头 `Idempotency-Key`；超时 30s 重试 3 次（仅幂等安全方法自动重试）；错误码 `OK / PARAM_INVALID / AUTH_DENIED / TENANT_ISOLATION / QUOTA_EXCEEDED / TOOL_TIMEOUT / UPSTREAM_FAILED / APPROVAL_REQUIRED / IMAGE_TOO_LARGE / UNSAFE_CONTENT / NOT_FOUND`。

| 工具 | Scope | 入参 | 出参 | 备注 |
|---|---|---|---|---|
| order.query | order:read | `{order_id, user_id}` | `{status, items[{sku,size,qty,price}], total, address_masked, tenant_id}` | 必校验订单归属 |
| logistics.query | order:read | `{order_id}` | `{nodes[{time, desc}], eta}` | 节点卡片渲染 |
| stock.query | stock:read | `{sku, size}` | `{available, eta_restock}` | 大促缓存 30s |
| coupon.query | promo:read | `{user_id}` | `{coupons[], rules}` | 叠加规则由引擎算 |
| refund.create | trade:refund | `{order_id, reason, amount, evidence_urls[]}` | `{refund_id, status:WAITING_APPROVAL}` | 恒进审批，不直执 |
| image.inspect | vision:inspect | `{image_urls[], session_id}` | `{category, confidence, bbox?, desc, safe_pass}` | <0.6 转人工 |
| kb.retrieve | kb:read | `{query, top_k=5}` | `{docs[{title, snippet, source, score}], trace}` | 带 tenant+生效期过滤 |

审批：`POST /approvals/{id}/approve {modified_args?}` / `.../reject {reason}`，鉴权 `approval:write` + 同租户 + 技能组。

流式：`POST /api/v1/agent/chat/stream` SSE `text/event-stream`，事件见 FR-1.1；长任务 >30s 返回 `{task_id}` 转 `GET /tasks/{id}` 轮询 / WS。

---

## 附录 B：核心建表（PostgreSQL，最小闭环）

```sql
create table tenants(id uuid primary key, name text not null, plan text default 'trial', quota_tokens bigint default 1000000, created_at timestamptz default now());
create table users(id uuid primary key, tenant_id uuid references tenants(id), external_id text, role text, created_at timestamptz default now());
create table sessions(id uuid primary key, tenant_id uuid not null, user_id uuid not null, channel text, status text default 'active', created_at timestamptz default now());
create table messages(id uuid primary key, session_id uuid not null, role text, modality text, content text, attachments jsonb default '[]', citations jsonb default '[]', trace_id text, created_at timestamptz default now());
create index on messages(session_id, created_at);
create table tasks(id uuid primary key, tenant_id uuid not null, user_id uuid not null, agent_id text, status text, input jsonb, output jsonb, error jsonb, checkpoint jsonb, created_at timestamptz default now(), updated_at timestamptz default now());
create table approvals(id uuid primary key, tenant_id uuid not null, session_id uuid, action text, args jsonb, status text default 'pending', approver uuid, reason text, created_at timestamptz default now(), decided_at timestamptz);
create table tool_calls(id uuid primary key, trace_id text, tenant_id uuid, user_id uuid, name text, args jsonb, result jsonb, latency_ms int, created_at timestamptz default now());
create table kb_docs(id uuid primary key, tenant_id uuid not null, title text, content text, channels text[] default '{all}', valid_from timestamptz, valid_to timestamptz, version int default 1, created_at timestamptz default now());
create table audit_logs(id uuid primary key, tenant_id uuid, actor uuid, action text, target text, detail jsonb, created_at timestamptz default now());
create table cost_records(id uuid primary key, tenant_id uuid, session_id uuid, model text, prompt_tokens int, completion_tokens int, cost_cents int, created_at timestamptz default now());
-- 所有业务查询强制 where tenant_id = :tid；订单类再 join 校验归属；审计表只追加不改。
```

---

## 附录 C：验收 Checklist（发布门禁）
- [ ] 三模态 E2E 通，弱网/断线重连过
- [ ] 黄金集 ≥500，解决率/幻觉/引用达标
- [ ] 瑕疵集 F1/召回达标，低置信转人工演示
- [ ] 退款 100% 进审批，越权测 0 泄漏，极限词/PII 过滤过
- [ ] 1000 混合压测 + 首字 P95 + 熔断降级演示
- [ ] CI 全绿 + SBOM + 扫描 + ArgoCD 灰度回滚 <5min
- [ ] 成本归因对账误差 <5%，SLO 大盘 + 告警 + 留痕 ≥6 个月可查
