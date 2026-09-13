# RAG 知识库构建、检索与治理规范（在线问答侧强制链路）

> 链路：Query → 双路召回（向量语义 + 关键词）→ RRF 融合 → bge-reranker 重排 → 治理双阶段过滤 → 多样性裁剪 → 阈值拒答 → 生成 + 引用 + faithfulness。

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

## 2. 召回两路 + 融合重排

```python
# ---------------- 双路召回 ----------------
vec_hits = await vector_store.search(emb, top_k, {"tenant": t, "level__in": visible})
kw_hits = await keyword_store.search(query, top_k, {"tenant": t})
# ---------------- RRF 融合 + 重排 ----------------
fused = rrf(vec_hits, kw_hits)
ranked = await reranker.rerank(query, fused)  # bge-reranker，不可用回退分数排序
```

- 参数全进 `Settings`：`TOP_K/RRF_K/RERANK_TOPN/THRESHOLD`，支持 `_HOT_FIELDS` 热更。
- 后端不可用 `status()` 可见，自动回退单路 + 片段摘要降级，绝不 500（参考 `chat.py::_demo_stream`）。

## 3. 治理双阶段过滤（必做）

1. 租户隔离：`flt tenant == access_context().tenant`，跨租户 0 召回。
2. 密级：`security_level ∈ 用户可见集`（运营可配）；`confidential` 需 `require_perm("kb")`。
3. 时效：`valid_from <= now <= valid_to`，过期自动不可见，大促话术靠版本切换。
4. 多样性裁剪：同 doc 至多 2 chunk，避免一文刷屏。
5. 阈值拒答：最高分 `< THRESHOLD` → `fail(2001,"这个问题我暂时没查到权威政策，已为你转人工",200)`，前端渲染拒答 + 转人工，不抛异常。

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
