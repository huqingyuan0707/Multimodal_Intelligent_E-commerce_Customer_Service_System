# ADR-0001：对话生成模型采用本地 Ollama（qwen2.5）的决策

- 日期：2026-09-13
- 状态：已落地
- 决策人：项目负责人（用户指定「AI 大模型采用本地部署的 Ollama 中的 qwen2.5」）
- 关联文档：`RAG知识库构建检索治理规范.md` §4（生成）/ `API接口与SSE事件协议规范.md` §4.2、§4.6（已同步）

## 1. 背景与约束

- 现状与问题：RAG 链路的生成段此前为模板拼装（片段摘要），无真实模型生成；开发机已装 Ollama 并 pull `qwen2.5:0.5b`，可零成本离线联调；云端 API 有密钥、费用与出网依赖。
- 约束：
  - 必须兼容适配层：业务代码禁止出现 URL / 模型名 / 密钥字面量（AGENTS.md §3 配置红线）。
  - 降级红线：模型不可用（未启动、超时、非 2xx、空回复）必须回落片段摘要，**绝不 500**。
  - 回滚要求：切回云端模型只改 `.env`，不改代码。
  - 本机网络环境有系统代理变量，localhost 请求必须 `trust_env=False`，否则被代理劫持连不上。

## 2. 候选方案

| 方案 | 优点 | 缺点 | 成本 |
|---|---|---|---|
| A：云端 OpenAI 兼容 API | 质量高、无本地资源占用 | 需密钥/计费/出网，离线不可演示 | 按 token 计费 |
| B：本地 Ollama qwen2.5（选定） | 完全离线、零成本、OpenAI 兼容协议、换模型只改配置 | 小模型（0.5b）答案质量有限、首 token 慢 | 本机算力 |
| C：transformers 进程内推理 | 无额外服务 | 拖慢启动、占内存、阻塞 IO 风险 | 本机算力 |

## 3. 决策

- 选择：B —— 经 `backend/app/services/llm_service.py`（适配层）调用 Ollama 的 OpenAI 兼容端点，默认 `LLM_MODEL=qwen2.5:0.5b`。
- 理由（对照约束逐条）：
  - 适配层收口：业务只调 `llm_service.complete()/probe()`，URL/模型名/密钥全在 `Settings`（`LLM_*`），满足配置红线；换方案 A 只改 `.env` 三行。
  - 降级：所有失败模式收敛为 `LlmUnavailableError`，由 `chat_service` 回落 `fallback_answer()`（片段摘要），信封仍 200、`degraded=true`。
  - 可观测：`GET /governance/status` 增 `llm` 巡检（probe 不抛异常，能区分「服务在线但模型缺失」）。

## 4. 后果

- 正面：离线可演示可测试（单测打桩 `_post/_get`，不依赖 Ollama 进程）；成本核算口径已埋（`usage.total_tokens → observability.record("llm", …)`）。
- 负面/风险 + 缓解：
  - 0.5b 模型可能编造引用 → `faithfulness()` 对越界 `[n]` 扣分，`done` 载荷暴露给前端提示；提示词硬约束「资料没有就不答」。
  - 本地小模型延迟高 → `LLM_TIMEOUT_SECONDS`（默认 60s）+ `LLM_REF_CHARS`（400）控上下文；超时即降级不挂请求。
- 回滚方案：`.env` 覆盖 `LLM_BASE_URL/LLM_MODEL/LLM_API_KEY` 即切云端；`LLM_ENABLED=false` 即全量回落模板（行为等同本 ADR 之前）。
- 可观测验证：`/governance/status` 的 `llm.available/detail`；`/api/v1/chat` 出参 `model`（`qwen2.5:0.5b` 或 `template`）与 `degraded`。

## 5. 落地清单

- [x] 代码适配层改动（`llm_service.py` 网关 + `chat_service.py` 只认网关，无 URL/模型名字面量）
- [x] Settings 更新（`LLM_*` 九项）+ `.env.example` 注释（pull/serve 提示）
- [x] 降级与巡检（`LlmUnavailableError → fallback_answer`；`probe()` 进 `/governance/status`）
- [x] 规范文档同步（API 规范 §4.2/§4.6、RAG 规范 §4）+ 单测 41 项全绿（打桩，不依赖真实 Ollama）
