# API 接口与 SSE 事件协议规范（本项目强制执行）

> 对齐：`skills/backend-code-style/SKILL.md` + `skills/frontend-code-style/SKILL.md`
> 目标：前后端联调零歧义，接口改动可自查 `openapi.json`，失败可定位 `trace_id`。

## 1. 基础约定

- BaseURL：`/api/v1`，前端经 `src/api/index.ts` 唯一入口，禁止页面直写 `fetch`。
- 认证：`Authorization: Bearer <reai_token>`，token 存 `sessionStorage.getItem('reai_token')`。SSE 同样必须带头，缺头 401 会导致本地模拟但服务端无记录。
- 统一响应信封，禁止裸返回：
```python
# 后端
from app.core.responses import ok, fail
return ok({"items": items}, "批量导入任务已提交")
return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
```
前端 `request<T>` 自动解包 `{code,msg,data,trace_id}`，`code!==0` 抛带 `code` 的 Error。
- 面向用户 `msg` 必须中文、可操作，如“内容与当前版本一致（SHA256 相同），已跳过重复入库”。
- GET query 一律 `encodeURIComponent`；上传用 `FormData`，绝不手设 `Content-Type`。
- 版本：URL v1，破坏性变更升 v2；幂等写操作支持 `Idempotency-Key` 头。
- 类型：后端 PEP604（`str | None`/`list[dict]`），不用 `Optional[]`；前端禁止新增 `any`，用 `unknown` + 守卫。

## 2. 错误码（`core/exceptions.py::ErrorCode`，新增必须落号段）

| 号段 | 含义 | 常用码 |
|---|---|---|
| 1xxx | 通用 | 1000 OK / 1001 PARAM_INVALID / 1002 UNAUTHORIZED(等同HTTP401走handle401) / 1003 FORBIDDEN / 1004 NOT_FOUND / 1005 QUOTA_EXCEEDED / 1006 RATE_LIMITED |
| 2xxx | RAG对话 | 2000 LLM_FAILED / 2001 NO_EVIDENCE拒答 / 2002 CONVERSATION_LIMITED / 2003 UNSAFE_CONTENT / 2004 IMAGE_TOO_LARGE |
| 3xxx | 户型/业务 Skill | 3001 ORDER_NOT_FOUND / 3002 ORDER_NOT_OWNED(越权) / 3003 REFUND_NEED_APPROVAL / 3004 STOCK_SHORTAGE(库存不足) / 3005 ORDER_STATE_ILLEGAL(订单状态非法) / 3006 COUPON_EXHAUSTED(券预算不足) / 3007 RISK_BLOCKED(风控拦截转人工) |
| 4xxx | 任务/工具 | 4001 TASK_NOT_FOUND / 4002 TASK_TIMEOUT(工具超时同码) / 4003 APPROVAL_REQUIRED / 4004 APPROVAL_DENIED / 4005 TOOL_NOT_FOUND / 4006 TOOL_SCOPE_DENIED / 4007 TOOL_CIRCUIT_OPEN / 4008 TOOL_CALL_FAILED / 4009 AGENT_STATE_ILLEGAL |
| 5xxx | 系统 | 5000 INTERNAL / 5001 UPSTREAM_FAILED / 5002 MODEL_UNAVAILABLE(走降级绝不500给用户) |

前端：HTTP401 或业务码 `1002` 一律走中央 `handle401()` 清登录态跳登录页，禁止各页面自写跳转。
后端：`main.py` 统一异常处理器收口信封——`BusinessError` 按号段码；`HTTPException 401/403/404` 转 `1002/1003/1004`；参数校验转 `1001`；未知异常转 `5000`（中文可操作，不泄露堆栈）。
前端：`src/api/http.ts::request` 自动解包（`code!==0` 按 `ERROR_MESSAGES` 转中文抛错，`err.code` 保留供 `2001` 拒答等分支判断）；`dispatch` 保留供 FormData/特殊场景。

## 3. 认证鉴权与用户隔离（安全红线）

后端：
```python
# app/api/v1/router.py
api_router.include_router(chat.router, dependencies=[Depends(get_current_user)])
# 敏感端点再加
@router.post("/documents/upload", dependencies=[Depends(require_perm("kb"))])
```
- 绝不信任请求体里的 `tenant_id/user_id` 做权限判断。可见范围一律 `governance.access_context()`（从 Token 的 ContextVar 推导）。
- service 层取用户用 `current_user()`（`core/user_context.py`），由 `get_current_user`（async）写入。
- 记忆/检索读写键必须是 `(tenant, Token用户名, thread)` 同一口径。
- 订单类必校验归属，否则 `3002`。
- **鉴权参数全部下沉 `Settings`**：`ACCESS_TOKEN_EXPIRE_SECONDS` / `JWT_ALGORITHM` / `PASSWORD_HASH_ITERATIONS` / `PASSWORD_SALT_BYTES` / `ROLES_SEPARATOR` / `SEED_*`，禁止硬编码密钥、算法、有效期、哈希代价。
- **生产护栏（`Settings._guard_prod`）**：`ENV=prod` 时若沿用默认 `JWT_SECRET`、密钥短于 32 字符，或 `SEED_ON_START` 未置 `false`，**加载配置即抛错**（fail-fast，宁可起不来也不带演示密钥上线）。
- 角色文本解析唯一口径 `security.split_roles()`（分隔符走 `ROLES_SEPARATOR`），种子写入与登录读取必须同源，禁止各处再写一遍 `split(",")`。
- 改 `PASSWORD_HASH_ITERATIONS` 会让存量 `pwd_hash` 全部验不过，必须同步重刷密码（`.env.example` 已标注）。

前端：
- 401 中央处理；按钮级 `v-permission` + 路由 `meta.roles`；敏感操作先 `ElMessageBox.confirm`，结果 `ElMessage` 反馈。

## 4. REST 端点清单

### 4.1 认证
- `POST /auth/login {username,password}` → `ok({token, user:{name, tenant, roles[], perms[]}})`。前端存 `reai_token`。
  - 入参为空 → `400` + `1001`；账号不存在 / 密码错误 → `401` + `1002`（msg「用户名或密码错误」）。
  - 登录请求**豁免中央 `handle401`**（`request(..., {authRedirect:false})`），否则密码错会被整页刷新、提示丢失。
- `GET /auth/me` → `ok({name, tenant, roles[], perms[]})`。401 则 `handle401()`。
- `POST /auth/logout` → `ok(null, "已退出登录")`。JWT 无状态，服务端仅确认身份，前端负责清 `reai_token`。
- `POST /auth/switch {username}` → `ok({token, user})`（顶栏“切换用户”免密代入，msg「已切换到用户X」）。仅 `admin` Scope 可调（`has_scope` 与 `require_perm` 同源），目标须与操作人同租户；非 admin → `403` + `1003`（「仅管理员可切换用户」），目标不存在/跨租户 → `404` + `1004`。成功记 `auth.switch` 审计（actor=操作人，target=目标，detail 含 from/to）；新 token 与 login 同结构，后续租户隔离自动按目标口径生效。普通用户切号走退出后登录页重登（`?redirect=` 回跳）。
- 本项目「角色即权限」：`perms` 与 `roles` 同值 —— `roles` 供菜单/路由 `meta.roles` 过滤，`perms` 供按钮级判断；服务端 `require_perm()` 才是真拦截。
- 种子账号由后端启动时幂等灌入（`SEED_*` 走 `Settings`，生产置 `SEED_ON_START=false`），无账号可登录不再是「清库即失联」。
- 开发默认账号：**租户 `demo-tenant` / 用户名 `admin` / 密码 `admin123` / 角色 `cs,kb`**（`.env` 的 `SEED_*` 可覆盖）。种子幂等且**不覆盖已存在账号**，改 `SEED_PASSWORD` 只对新建账号生效。

### 4.2 对话（非流式，调试/短问答）
- `POST /agent/chat {query, thread_id?, security_level?, client_msg_id?, image_ids[]?, inspections[]?}` → `ok({answer, references[], guard:{pass,degraded,empty,rejected}, faithfulness, model, degraded, trace_id, session_id, vision[], need_human, context{rounds,tokens,dropped,summarized}, tool_calls[], orchestration{notes[],empty,approval}, handoff{hit,enabled,code,label,reason,priority,matched[],matched_rules[],applied,handoff_status,session_id}})`（规范路径；`/chat` 为兼容别名，行为一致）。
- 入参 `thread_id` 命中本人会话则复用，否则新建（标题取问题前 20 字，他人/异租户 id 视为未传）；`client_msg_id` 为前端每次发送生成的幂等键，同（会话，键）重调只落一行，重放不再调模型。
- 用户消息与助手回复（含引用/guard/忠实度/trace）双双落 `messages` 表，刷新后 `GET /sessions/{id}` 可回放。
- 生成走适配层 `llm_service`（本地 Ollama `qwen2.5`，ADR-0001）；模型不可用**不 500**：降级片段摘要，`degraded=true`、`model="template"`。
- `faithfulness`：回答内 `[n]` 引用越界按比例扣分（无引用记 0.9），低分前端可提示核对来源。
- `tool_calls[]`：本轮检索段经 Agent 编排真调的工具记录（形状同 `POST /agent/tools/{name}/invoke` 出参，含 `scope/attempts/latency_ms/trace_id`，前端 `ToolCallCard` 直接渲染）；走回落直调时为空数组，帧形不随分支变化。
- `orchestration{notes[]}`：编排说明（中文可读，空数组 = 规划按预期命中）。固定文案：`命中「退款」但缺少必填参数（如订单号/SKU），已回落知识库检索` / `当前身份无权调用 X，已回落知识库检索` / `X 未返回可用结果，已转人工跟进` / `该动作需人工审批，已生成审批单（账目未变动）` / `编排不可用，已回落直连检索`。
- `2001` 表示无据拒答，前端渲染拒答话术 + 转人工按钮，不当错误抛异常（拒答同样落库，`guard.rejected=true`）。
- `handoff`：本轮转人工规则表判定结果（C 步）。`hit=true` 表示命中某条规则（`code/label/reason` 是坐席可读依据，`matched[]` 列出所有命中规则，取 `priority` 最小者挂起）；`applied=true` 表示确实把会话挂进了待接队列（已 `handling/resolved` 或已 `pending` 时为 `false`，`handoff_status` 回当前状态）。`guard.empty`（工具空手）与 `guard.degraded` 是「连续未解决 / 连续降级」的计数依据，坐席代回（`guard.by="agent"`）即清零。

### 4.3 会话与记忆（三层：Session→Message→Context，对齐 FR-1.4）
- `GET /sessions?page=1&size=20` → 分页对象 `{items[{id,title,summary,message_count,created_at,updated_at}], total, page, size}`（按 `tenant+username` 隔离、最近活跃倒序；空数据 `items=[]` 不报错）。
- `POST /sessions {title?}` → 新会话落库（前端本地先建 `t-${Date.now()}` 占位，成功后以后端 `id` 为准）。
- `GET /sessions/{id}?page=1&size=50` → `{id,title,summary,messages[倒序],total,page,size,has_more}`（page=1 最新页；`has_more` 供前端“加载更早消息”；前端渲染前反转即正序）。404（跨租户/跨用户同 404）则回退 `@/mock` 演示数据。
- `PUT /sessions/{id} {title}` → 重命名（空标题 1001，超长截 20 字）。
- `GET /sessions/{id}/context` → 上下文视图 `{summary, rounds, tokens, dropped, budget, window_rounds}`（与 `run_text_turn` 装配同源：同 `load_window/build_history_block`，所见即所算，供坐席 Trace 调试）。
- `DELETE /sessions/{id}` → 需 confirm + 消息级联遗忘。
- 上下文装配（每轮）：落库本轮前取最近 `SESSION_HISTORY_ROUNDS`（默认 20）轮 → 满窗刷新 `sessions.summary` 规则摘要 → 摘要 + 窗口（多模态附件转写成 `[图：破洞 0.85]` 行）拼 `history` 进 LLM 解指代；超 `SESSION_TOKEN_BUDGET`（默认 8000，中文 1.5 字/token 统一口径）从旧往新丢轮；历史先经手机/身份证/邮箱正则脱敏。`done` 加法带 `context{rounds,tokens,dropped,summarized}`（向后兼容）。
- 前置地基：`sessions/messages` 表由 Alembic 基线迁移建表 + `d3f1a2b4c5e6` 补 `summary/updated_at`（只加列，旧库 server_default 回填）。

### 4.4 知识库
- `POST /documents/upload` FormData(`file, security_level?=internal, channels?=all, valid_from?=, valid_to?=`) → `ok({doc_id, sha256, skipped?})`，重复 SHA256 返回“已跳过重复入库”（敏感写，`require_perm("kb")` Scope 校验；超 `MAX_UPLOAD_BYTES` 1001；解析→切分→向量化全在 `document_service.ingest_upload`，记 `kb.upload` 审计）。
- `GET /documents?page=1&size=20&keyword=` → 分页对象 `{items[], total, page, size}`（租户隔离倒序，标题模糊筛选，空数据 `items=[]` 不报错；`items[]` 含密级/渠道/生效期/版本，不含正文）。
- `GET /documents/{id}` → 详情（含正文与全量元数据，供预览/编辑回显；跨租户 404）。
- `PUT /documents/{id} {title, content, security_level, channels[], valid_from?, valid_to?}` → 内容变则版本 +1，撞他篇内容 1001（敏感写，`require_perm("kb")`）。
- `DELETE /documents/{id}` → 需 confirm（敏感写，`require_perm("kb")`）；`POST /documents/reindex` → 落 `tasks` 行返回 `{task_id}`（敏感写，`require_perm("kb")`）。
- 上传失败 `fail(PARAM_INVALID,"请至少选择一个文件",400)`。

### 4.5 审批与任务
- `GET /approvals?status=pending&page=1&size=20&action=&keyword=` → 服务端分页对象 `{items[], total, page, size}`（默认待办；`status` 非法 `1001`；`action` 精确匹配四类；`keyword` 模糊搜对象/申请人/原因；空结果 `items=[]` 不报错；只传 `status` 不传 `page/size` 时兼容回数组，供存量调用过渡）。列表可见 `cs/shop/stock/ops/admin` 及各域读写真令牌（客服可看待办），批/驳仅 `shop/ops/admin`；批/驳同步记 `approval.approve|reject` 审计（actor/target/前后状态）。
- `POST /approvals/{id}/approve {modified_args?, reason?}` / `POST /approvals/{id}/reject {reason}`（驳回理由必填留痕；重复处理 `4004`；跨租户 `404`；批准先执行生效动作再改状态，同事务失败整体回滚）。
- `GET /tasks?page=1&size=20&status=` → 本人维度真实列表（空数据 `[]` 不报错）；`POST /tasks {type, payload}` → `{task_id}`；`GET /tasks/{id}` → `{status, progress, result}`（跨租户 404）。SSE 任务类事件另含 `progress/complete/error`。
- `POST /documents/reindex` → 建 `kb.reindex` 任务行即 via `BackgroundTasks` 真实执行（租户全部分块重建），`GET /tasks/{id}` 轮询 `running → done{docs, chunks}`（异常落 `error`，不断流）。

### 4.6 治理与可观测
- `GET /governance/status` → `{llm, vector{backend,model,dim,vectors}, keyword, reranker, thresholds{top_k,rrf_k,db_threshold,diversity_per_doc,faithfulness_warn}, hot_fields}`（`llm_service.probe()` + `vector_store.status()` + `rerank_service.status()` 实测，绝不抛异常）。
- `POST /mining/feedback {message_id, vote, comment?}` → `ok({id})`（跨租户 404；记 `mining.feedback` 审计）；`GET /mining/candidates` → `{items[{feedback_id,message_id,session_id,vote,comment,query}], total}`（差评 + 无引用拒答补位，租户隔离）。
- `GET /observability/summary` → 耗时/召回/拦截/token 成本聚合（后端 `_record() → observability.record()` 必埋，检索/生成/Mining 每步带 `tenant/trace_id`）。

### 4.7 B端商家后台（对齐 FRDv2 附录 D，同基座 JWT/Scope/幂等键/审计）
> 已实现（本期，路由级 `get_current_user` + 端点 `require_any_perm`）；采购/财务/大屏为 P2 待建。
- 商品：`GET /goods?keyword=&status=&page=&size=`（SPU 列表含 SKU 矩阵与聚合 attrs/库存可用量，`goods:read|write`）、`POST /goods/skus/{sku_id}/price-change {new_price,reason}`（恒进审批返回审批单，`goods:write`）、`PUT /goods/skus/{sku_id} {barcode?,status?}`（行内编辑不含价格）、`PUT /goods/{product_id}/status {status}`（on|off|draft|archived）。
- 库存：`GET /inventory?warehouse_id=&sku_id=&only_warn=`（qty/reserved/locked/available/warning，available=qty-reserved-locked 唯一口径）、`GET /inventory/warehouses`、`GET /inventory/moves?sku_id=`（流水审计，`stock:read|write`）；`POST /inventory/moves {kind:in|out|move,…}`（move 带 `to_warehouse_id` 自动拆两行流水，缺货 `3004`；`adjust` 仅系统内部盘点审批写入，不接受直接提交）、`POST /inventory/stocktake {lines[{warehouse_id,sku_id,counted}],reason}`（差异恒进审批、账实一致免审）、`POST /inventory/replenish {sku_id,qty,reason}`（恒进审批）（`stock:write`）。
- 订单：`GET /orders?status=&platform=&keyword=`（列表不含收件人 PII，含 `allowed_actions` + 面单 `logistics_id/logistics_status`）、`GET /orders/{id}`（详情+面单+售后单，跨租户 404）、`POST /orders/{id}/ship {company,tracking_no}`（仅「待发货」可发否则 `3005`；公司限 `Settings.LOGISTICS_COMPANIES` 枚举、单号过 `TRACKING_NO_PATTERN` 否则 `1001`）（`order:read|fulfill`）。
- 售后：`POST /aftersales {order_id,reason,amount,trace_id,evidence}`（状态须 shipped/completed 否则 `3005`；金额> `REFUND_APPROVAL_LIMIT_CENTS` 恒进审批返回 `{need_approval,approval_id,status:"approving"}`）、`GET /aftersales?limit=`（`order:fulfill`，列表与详情均回 `evidence[] + status_label`，与建单入参同一口径）。
- 审批联动：`POST /approvals/{id}/approve|reject` 已对接 `approval_service` 处理器——改价应用 / 补货入库 / 盘点调账（可传 `modified_args.lines` 修正实盘数）/ 退款执行；执行前服务端复校验，非法则整体回滚。
- 采购：`POST /purchase`、`POST /purchase/{id}/approve|receive|qc`（`purchase:write`，P2）；供应商 `GET/POST /suppliers`（P2）。
- 财务：`GET /finance/bills`、`POST /finance/settle`（`finance:read/write`，P2）。
- 大屏：`GET /screen/summary?range=today|week`（`screen:read`，Redis 缓存 1min，PII 脱敏，P2）。
- B端单据写操作必须带 `Idempotency-Key`；采购/调拨/报损/超阈值退款恒进审批流。

### 4.8 横向域端点（对齐 FRDv2 FR-10.6-10.8/FR-12，附录 D 同源）
- 营销：`GET/POST /promos`（建活动 `budget` 单位张计数，`valid_from/valid_to` 空串=不限，格式 `YYYY-MM-DD HH:mm:ss` 否则 `1001`；列表回 `remaining/valid_from/valid_to/created_at`）、`POST /coupons/grant {promo_id, user_ref}`（幂等 `idem_key` + 预算原子扣减，超预算 `3006`，回 `idem_key/created_at` 供对账）。
- 物流：`GET /logistics/companies`（`Settings.LOGISTICS_COMPANIES` 唯一口径）、`POST /ship`、`POST /logistics/exception`（异常件自动建售后单；`track` 回 `status_label`，状态含 `exception` 异常位）。
- 评价：`GET /reviews?level=bad`、`POST /reviews/{id}/reply|ticket`（差评 2h SLA 倒计时由前端算）。
- 风控：`GET /risk/events`、`POST /risk/{id}/pass|block`（`risk:review`，拦截 `3007`，禁全自动封号）。
- 消息：`POST /notify/send {channel, template, user_ref}`（`notify:send`，频控 429 走 `1006`）。
- 工单：`POST /tickets`、`POST /tickets/{id}/transfer|close`（关闭 `conclusion` 必填，否则 `1001`）。

### 4.9 管理后台（对齐 FRDv2 FR-8 + 页面设计 §3.8，同基座 JWT/admin 权限/审计）
> 已实现（本期，路由级 `get_current_user` + 端点 `require_any_perm("admin")`，全局视角）；密钥明文/SLO 告警为 P2 待建。
- 概览：`GET /admin/overview` → `{tenant_total,user_total,suspended,audit_total}`（指标卡）。
- 租户：`GET /admin/tenants?keyword=&plan=&status=&page=1&size=20`（分页默认 20）、`POST /admin/tenants {code,name,plan?,quota_tokens?,quota_concurrency?}`（编码唯一重复 `1001`，配额缺省走 `Settings.DEFAULT_QUOTA_*`）、`GET /admin/tenants/{code}`、`PUT /admin/tenants/{code}/quota {quota_tokens,quota_concurrency}`（正数校验，前端双重 confirm）、`POST /admin/tenants/{code}/status {status:active|suspended|disabled}`（欠费停服即 suspended）。
- 用户：`GET /admin/users?tenant=&keyword=&page=&size=`、`PUT /admin/users/{id}/roles {roles:"cs,admin"}`（空角色 `1001`）。
- 审计：`GET /admin/audits?tenant=&action=&keyword=&page=&size=`（只读倒序，`tenant.create/quota/status + user.roles` 全留痕）。
- 写操作幂等：`Idempotency-Key` 由前端 `dispatch(idempotent:true)` 自动带；变更类操作同步记 `audit_logs`（只追加不改）。

### 4.10 多模态（对齐 FRDv2 FR-1 + 执行步骤 A，同基座 JWT/租户隔离/审计）
> 图片：上传 → 对象存储（数据模型 §5 布局）→ NSFW/PII 预检 → VLM 瑕疵检测 → 拼 LLM 上下文 → 置信 <0.6 转人工；语音：ASR 转写 + TTS 开关/音色。
- `POST /multimodal/images` FormData(`file, session_id?=`) → `ok({file_id, url, inspection{category, confidence, desc, need_human, degraded, safe_pass, bbox}})`。超 10M → `2004`；NSFW/PII 命中 → `2003`（中文可操作，均不抛 500）。
- `POST /agent/chat` / `POST /agent/chat/stream` 加法字段：`{image_ids[], inspections[]}`（上传步回执原样透传；后端按类别白名单清洗 + 置信度钳 0-1 + `need_human` 按 `VLM_CONFIDENCE_THRESHOLD` 重算，不信任前端）。
- `POST /multimodal/speech/transcribe` FormData(`file, session_id?=`) → `ok({file_id, url, text, confidence, need_confirm, degraded})`（≤60s/≤5M；低置信 `need_confirm=true` 回问确认）。
- `GET /multimodal/speech/tts-config` → `ok({enabled, voice, voices})`（默认晓晓，前端下拉同源）；`POST /multimodal/speech/synthesize {text, voice?}` → `ok({text, voice, enabled, degraded})`（前端 WebSpeech 播放 + 波形）。
- `GET /multimodal/media/{file_id}` → 文件流（租户隔离，跨租户 404）。
- 可调全进 `Settings`：`MEDIA_DIR/IMAGE_MAX_COUNT/IMAGE_MAX_BYTES/IMAGE_ALLOWED_TYPES/VLM_*/ASR_*/VOICE_MAX_*/TTS_*`（`VLM_CONFIDENCE_THRESHOLD/ASR_CONFIDENCE_THRESHOLD` 进 `_HOT_FIELDS` 热更）；`GET /governance/status` 加法回 `vlm/asr`（含阈值）与 `thresholds.vlm_confidence/asr_confidence`。
- openapi 自查说明：`backend/openapi.json` 尚未落库（pre-commit 显示 SKIP），本轮以 `app.openapi()` 导出核对：新增 5 条 `/multimodal/*` path，总 63 paths，`chat` 加法字段向后兼容。

### 4.11 坐席工作台（对齐 FR-7 转人工闭环 + 页面设计 §3.2，同基座 JWT/租户隔离/幂等/审计）
> 状态机：`none`（AI 接待）→ `pending`（待接）→ `handling`（已认领）→ `resolved`（已解决，可被买家再次 `handoff` 重开）。
> 权限：`handoff` 是买家自助口（`get_current_user`，owner 校验）；队列/认领/转接/解决/代回/备注/Trace 一律 `require_any_perm("cs","admin")`。可见范围由 Token 推导（`governance.access_context()`），**不读请求体 tenant/user**。
- `GET /workbench/queue?status=&q=&page=1&size=20` → 分页对象 `{items[{id,title,username,created_at,updated_at,message_count,handoff_status,handoff_label,assignee,handoff_reason,resolution,last_message}], total, page, size}`。`status` 空/`open` = 待接+处理中；`pending/handling/resolved/none` 精确过滤（其他值 `1001`「队列状态非法」）；`q` 模糊匹配标题/买家名（≤64 字）；`last_message` 为最新一条预览（截 40 字）；按 `updated_at desc` 排序，空结果 `items=[]` 不报错。
- `GET /workbench/handoff-rules` → `ok({enabled, miss_streak_threshold, degrade_streak_threshold, rules[{code,label,reason,priority,signal,threshold,enabled}]})`。转人工触发规则表**只读**口径：阈值取自 `Settings.HANDOFF_*`（`HANDOFF_ENABLED/HANDOFF_MISS_STREAK_THRESHOLD/HANDOFF_DEGRADE_STREAK_THRESHOLD` 可热更），规则表本体在 `services/handoff_rules.py`；供坐席核对「这个会话为什么进了队列」，`require_any_perm("cs","admin")`。
- `POST /workbench/sessions/{id}/handoff {reason?}` → `ok(队列行)`，`none|resolved → pending`（买家侧「转人工」入口，二次点击幂等）；聊天链路与 Agent 编排的**自动挂起一律经规则表** `handoff_rules` 判定（挂载点 `services/handoff_service.py::auto_handoff`）：喊人工 / 情绪激烈 / 敏感操作送审 / 图检低置信 / 无据拒答 / 编排空手 / 连续 3 次未解决 / 模型连续 3 次降级（命中多条取优先级最高者，其余落 `matched` 审计），命中才挂起（`mark_pending_if_idle`，不抢 `handling/resolved`）；坐席代回即把「连续未解决」计数清零。
- `POST /workbench/sessions/{id}/claim` → `ok(队列行)`，`pending|none → handling` + `assignee=Token 用户名`；已被他人认领 → `1001`「已被 XX 接管，转为只读围观」（前端据此切只读态，不弹系统错误）。
- `POST /workbench/sessions/{id}/transfer {assignee}` → `ok(队列行)`，`assignee` 必填且限本租户坐席名；`pending` 顺手升为 `handling`；已解决 `1001`。
- `POST /workbench/sessions/{id}/resolve {conclusion?}` → `ok(队列行)`，`handling|pending → resolved` + `conclusion`（≤500 字，落 `sessions.resolution`）；重复解决 `1001`。
- `POST /workbench/sessions/{id}/reply {content}` → `ok(message)`，**仅 `handling` 会话可发**（未认领 `1001`「请先认领会话再代回」）；落 agent 行：`citations=[]`、`guard={pass:true, by:"agent", agent:<坐席名>}`、`faithfulness=1.0`、新 `trace_id`，买家侧历史回放即见（不重进队列）；内容 1..2000 字，超长 `1001`。
- `GET /workbench/sessions/{id}/notes` → `ok([{id,session_id,author,content,created_at}])`（创建时间正序；买家无查询口，天生不可见）。
- `POST /workbench/sessions/{id}/notes {content}` → `ok(备注行)`，`author` 取 Token 用户名，内容 1..500 字（空/超长 `1001`）；写操作带 `Idempotency-Key`。
- `GET /workbench/sessions/{id}/trace?size=50` → `ok({session, messages[], context{summary,rounds,tokens,dropped,budget,window_rounds}})`。与买家侧 `get_session_detail` **完全同源**（同 `message_to_dict`、同 `context_service.load_window/build_history_block`），坐席所见即买家所得；`size` 1..200。
- 跨租户 / 不存在的会话一律 `404`「会话不存在或已过期」（不泄露存在性）。
- openapi 自查说明：本轮以 `app.openapi()` 导出核对，新增 9 条 `/workbench/*` path（含 `GET /workbench/handoff-rules`），总 **79** paths，其余端点未变。

### 4.12 Agent Runtime 与工具注册中心（对齐 FRD-3/FR-5 + 附录 A，同基座 JWT/租户隔离/审批/审计）
> 状态机：`IDLE → PLANNING → ACTING → OBSERVING → REFLECTING → DONE`，分支 `WAITING_APPROVAL / WAITING_HUMAN / FAILED`；非法流转 `4009`「状态流转非法：X → Y」（白名单见 `modules/agent/contracts.py::TRANSITIONS`）。
> 工具契约（附录 A 逐条对齐）：`order.query`/`logistics.query` = `order:read`、`stock.query` = `stock:read`、`coupon.query` = `promo:read`、`kb.retrieve` = `kb:read`、`refund.create` = `trade:refund`（`requires_approval=true`，非幂等）。
> 执行口径：超时 30s（`AGENT_TOOL_TIMEOUT_SECONDS`）→ 幂等工具退避重试 3 次（`AGENT_TOOL_MAX_RETRIES`，**非幂等工具恒 1 次**）→ 连续失败 3 次熔断 60s（`AGENT_TOOL_CIRCUIT_*`）。**业务拒绝（`BusinessError`，如订单不存在）不重试、不计熔断，原码上抛**；超时给 `4002`，其他依赖失败给 `4008`。全部分支（含被拒/超时/熔断）都写 `tool_calls` 审计，工具调用可回放。
- `GET /agent/tools` → `ok({total, items[{name, scope, description, params(JSON Schema), idempotent, requires_approval, approval_action, timeout_seconds, max_retries, breaker{failures, open, last_error, recent_latency_ms}}]})`。登录即可读（Agent Studio 工具页直接渲染）；注册中心为空时 `msg` 提示且不报错。**出参绝不含 handler**（可调用对象不下发）。
- `GET /agent/tools/{name}` → `ok(同上单项)`；未注册 → `4005`「工具不存在：X，可用：A/B/C」。
- `POST /agent/tools/{name}/invoke {args, session_id?, trace_id?}` → `ok({tool, status:"ok", scope, idempotent, requires_approval, approval_required, approval_id, args, result, attempts, latency_ms, timeout_seconds, trace_id})`。受控试调（ToolCallCard 透明展示）：Scope 不命中 → `4006` + HTTP 403；入参不全 → `1001`（附中文逐条原因）；熔断中 → `4007` + HTTP 503。敏感工具调用后 `approval_required=true` 且返回 `approval_id`，**账不动**（`msg` 明示「已提交审批，待人工确认后生效」）。
- `POST /agent/run {query, session_id?, tool_args?, trace_id?}` → `ok({task_id, state, state_label, query, session_id, cursor, steps[{tool,args,reason}], results[], notes[], answer, approval_id, error, trace_id, updated_at})`。规则规划（可解释，命中即用；缺必填参数**不硬调**，回落 `kb.retrieve` 并在 `notes` 说明）。每步落 `tasks.checkpoint` 并提交，崩溃可续跑；命中敏感工具即挂 `WAITING_APPROVAL`；检索零召回挂 `WAITING_HUMAN` 并同步经规则表 `auto_handoff` 进坐席待接队列（不抢已认领）。
- `GET /agent/runtime/{task_id}` → `ok(快照同形)`；跨租户 / 无检查点 → `4001`「任务不存在或已过期」/「该任务不是 Agent 编排任务，无检查点」（不泄露存在性）。
- `POST /agent/runtime/{task_id}/resume` → `ok(快照)`，从 `cursor` 续跑剩余步骤，**不重放已完成步**。审批未决 → `4003`「该轮已提交审批，请等审批通过后再继续推进」（HTTP 409），绝不放行绕过人工；已驳回 → 收敛 `FAILED`。
- 任务态映射：`DONE → tasks.status=done`，其余挂起/失败态留 `running/error`，`tasks.output` 落 `{state, answer, steps}`（`GET /tasks/{id}` 可轮询）。
- 对话主链接线（`/agent/chat` 与 `/agent/chat/stream`，`/chat` 别名同）：检索段不再直调 `knowledge_service.retrieve`，改由 `runtime.orchestrate()` 规划 → `executor.call()` 执行 → `kb.retrieve` 结果回喂同一 `build_messages/validate_references` 口径。**不建 `tasks` 行、不落检查点**（对话轮次不是任务，否则每条买家消息都刷任务中心）；业务查询事实以 `【业务查询】` 块注入提示词（不占 `[n]` 引用编号）。治理口径不变：`refs` 仍来自 `kb.retrieve`（租户/密级/生效期/渠道过滤在 service 内），敏感工具（`refund.create`）**不自动触发**——缺必填参数即回落检索。编排不可用（开关关闭 / 连接器未装载 / 内部异常）一律回落直连检索并记 `agent.degraded` trace，**绝不 500、绝不把「工具没装上」放大成 `2001`**。
- 可调全进 `Settings`：`AGENT_TOOL_TIMEOUT_SECONDS / AGENT_TOOL_MAX_RETRIES / AGENT_TOOL_CIRCUIT_THRESHOLD / AGENT_TOOL_CIRCUIT_COOLDOWN_SECONDS / AGENT_TOOL_RETRY_BACKOFF_SECONDS / AGENT_MAX_STEPS / AGENT_CHAT_ORCHESTRATE`（前四项进 `_HOT_FIELDS`；`AGENT_CHAT_ORCHESTRATE=false` 即对话链一键回退直调）。
- 启动注册：`main.py::lifespan → modules/agent/bootstrap.startup()` 幂等装载 6 个连接器；注册失败只告警不阻断启动（编排是增强能力，缺它服务仍须可用）。
- openapi 自查说明：本轮以 `app.openapi()` 导出核对，新增 6 条 `/agent/*` path（`tools`、`tools/{name}`、`tools/{name}/invoke`、`run`、`runtime/{task_id}`、`runtime/{task_id}/resume`），总 **78** paths，其余端点未变。对话主链接线**不动路径与入参**，只在 `ok()` / `done` 载荷新增 `tool_calls[]` 与 `orchestration{notes[]}`（加法，向后兼容；老前端忽略即可）。配套：工具 Scope 令牌 `kb:read`/`vision:inspect`/`trade:refund` 已并入 `SEED_ROLES`（seed 侧只并集补齐，不覆盖存量密码与角色）。

## 5. SSE 流式协议（项目实际形态）

后端事件名固定：`source / phase(retrieving[/inspecting]/generating/validating) / message / done`（任务类另有 `progress/complete/error`；图文轮多一帧 `inspecting`，纯文本轮无此帧）。`done` 载荷必含 `references + guard + faithfulness + trace_id + session_id + tool_calls[] + orchestration{notes[]} + handoff{hit,code,reason,applied,handoff_status}`（`handoff` 是转人工规则表判定结果，加法，老前端忽略即可），图文轮加带 `vision[] + need_human`（前端渲染检测卡 + 低置信转人工按钮），多轮加带 `context{rounds,tokens,dropped,summarized}`（前端气泡小字透出用量）。每帧必带 `id:` 行（`{stream_id}:{seq}`，`stream_id` 由 `client_msg_id` 确定性派生，重放帧 id 相同），前端同流内按 id 去重，断线重连不重复拼接。`message` 负载为模型 token 级增量（在线时首字不等全文拼完）；降级模板/重放命中时为整段按 `SSE_CHUNK_CHARS` 切片，帧形与幂等语义一致。`validating` 帧在全文到齐后发出（流式下位于末尾 `message` 之后、`done` 之前）。

```python
"""聊天流 endpoint（对齐 API 规范 §5）"""
# app/api/v1/endpoints/chat.py
from fastapi.responses import StreamingResponse
from app.core.responses import ok  # 非流式用；流式按事件帧返回
import asyncio

async def _demo_stream(query: str):
    # 模型不可用时演示降级，绝不 500
    yield "event: message\ndata: {\"content\":\"演示模式：\"}\n\n"
    yield "event: done\ndata: {\"references\":[],\"guard\":{\"pass\":true},\"faithfulness\":1.0,\"trace_id\":\"demo\",\"session_id\":\"\",\"tool_calls\":[],\"orchestration\":{\"notes\":[]}}\n\n"

@router.post("/agent/chat/stream")
async def chat_stream(payload: ChatRequest, user=Depends(get_current_user)):
    async def gen():
        try:
            async for ev in service.stream_chat(payload, user):  # service 内阻塞调用走 to_thread
                yield f"event: {ev.type}\ndata: {ev.json()}\n\n"
        except Exception:
            async for ev in _demo_stream(payload.query):
                yield ev
    return StreamingResponse(gen(), media_type="text/event-stream")
```

- 阻塞 IO（模型推理、文件解析、Chroma）必须 `await asyncio.to_thread(...)` 或 `BackgroundTasks`，禁止在 async 直接调阻塞库。
- Nginx/Ingress 必须 `proxy_buffering off; proxy_read_timeout 3600s;`，多副本需粘性会话或共享状态。

前端固定范式（箭头函数 + try/catch + 带头）：

```ts
// src/composables/useAgentStream.ts
export const useAgentStream = () => {
  const onStreamChat = async (p: { query: string; threadId: string }) => {
    const res = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${sessionStorage.getItem('reai_token') ?? ''}`,
      },
      body: JSON.stringify(p),
    });
    const reader = res.body?.getReader();
    // 按 event: / data: 正则分帧 -> phase/message/done 分支；done 的 JSON.parse 必须 try/catch
    const onDone = (raw: string) => {
      try {
        return JSON.parse(raw) as { references: unknown[]; trace_id: string };
      } catch {
        return { references: [], trace_id: '' };
      }
    };
    return { reader, onDone };
  };
  return { onStreamChat };
};
```

- 断线重连 + 事件 ID 幂等；`done` 后合并引用与 `trace_id` 展示；401 进 `handle401()`。

## 6. 前后端分层示例

后端 endpoint 只做薄封装，业务进 `services` 纯函数（不依赖 FastAPI 对象）：
```python
"""会话服务（对齐 API 规范 §4.3）"""
# services/session_service.py
from app.core.user_context import current_user

async def get_session(session_id: str) -> dict | None:
    u = current_user()  # tenant/用户名同一口径
    return await repo.get(session_id, u.tenant, u.name)
```

前端页面只编排，逻辑进 `composables/useXxx`，跨页共享才进 Pinia setup 风格 store：
```ts
// src/stores/session.ts
export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([]);
  const loadSessions = async () => {
    try {
      sessions.value = await api.listSessions();
    } catch {
      sessions.value = mockSessions; // 降级演示
    }
  };
  return { sessions, loadSessions };
});
```

## 7. 联调门禁
`python -m py_compile <改动文件>`；接口改必 `openapi.json` 自查；跑对应 `tests/smoke_*.py`；后端 `ruff check .` + `ruff format --check .`（ruff 版本与 `.pre-commit-config.yaml` rev 钉死一致，当前 0.16.7）；前端 `pnpm lint`（0 errors）+ `pnpm format:check` + `pnpm typecheck` + `pnpm build`。CI 任一红灯不合并；红灯后 `ai-diagnose.yml` 自动出「哪里错了 + 修复建议」评论。
