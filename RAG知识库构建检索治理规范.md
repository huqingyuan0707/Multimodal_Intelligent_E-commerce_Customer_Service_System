# RAG 知识库构建、检索与治理规范（在线问答侧强制链路）

> 链路：Query → 三路召回（向量库 + TF-IDF + 关键词）→ RRF 融合 → rerank 重排 → 治理双阶段过滤 → 多样性裁剪 → 阈值拒答 → 生成 + 引用 + faithfulness。

## 0. 十三步全链路（本期实现口径，代码一一对应）

`上传 → 解析 → 分块 → 向量化 → 混合检索 → Rerank → 过滤 → 拼接 → LLM 生成 → SSE 流式 → 引用校验 → 落库 → Mining 闭环`，每步租户隔离 + 生效期过滤 + 审计留痕：

| 步 | 代码 | 租户/生效期/审计 |
|---|---|---|
| 上传 | `endpoints/documents.py::upload_document` + `document_service.ingest_upload` | `user.tenant` 显式传参 + `require_perm("kb")`；超限/非法密级 1001；`kb.upload` audit |
| 解析 | `services/doc_parse_service.py::parse_upload`（`to_thread`） | 多编码解码 + 清洗 + `MAX_UPLOAD_BYTES/CHARS` 门禁；`trace rag.upload` |
| 分块 | `document_service.split_chunks`（`##` 主题优先） | `KB_CHUNK_CHARS` 热更；`ord` 供引用定位 |
| 向量化 | `services/vector_store.py::upsert/embed_text` | 键 `{tenant}:{chunk_id}` 隔离；`HF_ENDPOINT setdefault` + 双检锁；`status()` 巡检 |
| 混合检索 | `knowledge_service.retrieve`（向量库 + TF-IDF + 关键词三路 RRF） | SQL 租户/密级 + Python 生效期/渠道；缺向量自动回退双路；`trace rag.retrieve` |
| Rerank | `services/rerank_service.py::rerank` | RRF 主序 + 余弦 + 关键词破平局；`status()` 巡检 |
| 过滤 | `services/rag_governance.py`（`is_valid_now/channel_visible`） | 租户/SQL + 密级 + 生效期 + 渠道 + 多样性 + 阈值；原因计入 trace |
| 拼接 | `chat_service.build_messages` | 单条 `LLM_REF_CHARS` + 总预算 `TOP_K` 倍封顶丢尾块 |
| LLM 生成 | `services/llm_service.py::complete` | `Settings.LLM_*`；`LlmUnavailableError` → 片段摘要 `degraded=true` 绝不 500 |
| SSE 流式 | `endpoints/chat.py::chat_stream` | `source/phase(retrieving/generating/validating)/message/done`；`id:{sid}:{seq}` 去重 |
| 引用校验 | `chat_service.validate_references` | `faithfulness` + 越界编号；`<FAITHFULNESS_WARN` 则 `guard.pass=False` 进 Mining |
| 落库 | `chat_service.run_text_turn` + `_record_cost_and_audit` | `messages` 双行 + `cost_records` 估算 + `chat.answer` audit，同事务 |
| Mining | `services/mining_service.py` + `endpoints/mining.py` | `feedbacks` 租户隔离 + 拒答补位候选 → 补知识 → `reindex` → 回归 |

## 1. 入库（写入删除侧）

```python
"""RAG 入库（对齐 RAG 规范第一节）

链路：解析 → 清洗 → 按业务主题切分 → SHA256 去重 → 向量/关键词双写
"""
```

- 阻塞 IO（文件解析、Chroma、模型推理）一律 `asyncio.to_thread` 或 `BackgroundTasks`。
- 按业务主题切分，不按固定段长；字段 `{title, content, tenant, channels, security_level, valid_from/to, version}`。
- `SHA256 相同 → 已跳过重复入库`（`ok` 中文 msg），不报错。
- 批量导入走 `tasks` 异步 + `progress/complete/error` SSE；删除必删向量 + 关键词 + chunks。
- Embedding 惰性单例 + `_meta_lock` 双检；`HF_ENDPOINT` 来自 `Settings`，下载前 `setdefault`。

服装主题：尺码/面料洗护/库存/优惠叠加/物流/退换/投诉；`security_level` 映射前端 `LEVEL_TAG={public:'公开',internal:'内部',confidential:'机密'}`，模板禁散落字面量。

## 2. 召回三路 + 融合重排

```python
# ---------------- 三路召回（P0 stdlib，向量库缺失自动回退双路） ----------------
store_hits = vector_store.search(tenant, query, chunk_ids)  # 向量路：哈希向量余弦
vec_hits = tfidf_cosine(query, chunks)       # TF-IDF 路：bigram TF-IDF 余弦
kw_hits = keyword_score(query, title, chunk)  # 关键词路：正文交叠 0.7 + 标题 0.3
# ---------------- RRF 融合 + 重排 ----------------
fused = rrf_fuse([store_hits, vec_hits, kw_hits])  # Σ 1/(RRF_K + rank)
ranked = rerank_service.rerank(fused, vec_hits, kw_hits)  # RRF 主序 + 双分破平局
```

- 参数全进 `Settings`：`TOP_K/RRF_K/RAG_DB_THRESHOLD/RAG_DIVERSITY_PER_DOC/KB_CHUNK_CHARS/EMB_DIM/FAITHFULNESS_WARN`，支持 `_HOT_FIELDS` 热更。
- 治理在 SQL + Python 双层收口：租户与密级进 SQL，生效期/多样性（同 doc 至多 2 块）在 Python；引用 `source` 定位到 `doc_id#ord` 块级。
- 后端不可用 `status()` 可见，自动回退单路 + 片段摘要降级，绝不 500（参考 `chat.py::_demo_stream`）。

## 3. 治理双阶段过滤（必做）

1. 租户隔离：`flt tenant == access_context().tenant`，跨租户 0 召回（向量键同口径）。
2. 密级：`security_level ∈ 用户可见集`（运营可配）；`confidential` 需 `require_perm("kb")`。
3. 时效：`valid_from <= now <= valid_to`，过期自动不可见，大促话术靠版本切换（`rag_governance.is_valid_now` 唯一口径）。
4. 渠道：`channels` 含 `all` 或命中请求渠道（`RAG_CHANNEL_FILTER` 开关，`channel_visible` 唯一口径）。
5. 多样性裁剪：同 doc 至多 `RAG_DIVERSITY_PER_DOC` chunk，避免一文刷屏。
6. 阈值拒答：三路最高分 `< THRESHOLD` → `fail(2001,"这个问题我暂时没查到权威政策，已为你转人工",200)`，前端渲染拒答 + 转人工，不抛异常。

记忆键 `(tenant, Token用户名, thread)` 与鉴权同口径， частных记忆不串。

## 4. 生成与可观测

- System Prompt 强制“仅基于引用回答，无据拒答”，输出必带 `references[]`（doc_id/chunk/source/score）。
- 生成模型走适配层 `services/llm_service.py`（ADR-0001）：默认本地 Ollama `qwen2.5:0.5b`，OpenAI 兼容协议，URL/模型名/阈值全在 `Settings.LLM_*`；资料按 `LLM_REF_CHARS` 截断编号注入（`[1]《标题》`），与引用校验同口径。
- 降级红线：`LlmUnavailableError`（未启用/超时/非 2xx/空回复）→ `fallback_answer()` 片段摘要，仍返回 200 且 `degraded=true`、`model="template"`，**绝不 500**。
- faithfulness：扫描回答中 `[n]` 引用，越界即按比例扣分（无引用记 0.9），随 `done` 载荷下发前端。
- 关键链路 `_record() → observability.record()`：耗时/召回数/拦截原因/token 成本（`usage.total_tokens`）/trace_id；`done` 事件回 `references+guard+faithfulness+trace_id`。
- 前端 `CitationList` 必显引用；复杂指标旁写一行中文口径注释。
- 反馈闭环：`feedbacks{message_id, vote, comment}` → mining 待补知识 → reindex → 回归评测。

## 5. 检索测试与发布门禁
运营后台 `检索测试` 输入 query 预览召回（分数/过滤原因可见）；黄金集回归不达标禁发布；`status()` 巡检向量/关键词/重排模型健康。
