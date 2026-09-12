---
name: backend-code-style
description: breath After modifying any Python code under backend/app or backend/tests, follow this skill so new code matches the project's FastAPI conventions (layering, envelope, RBAC, governance, tests).
---

# 后端代码风格（FastAPI · 本项目强制约定）

## 1. 分层（必须遵守）
- `api/v1/endpoints/*.py` 只做薄封装：参数解析 → 调 `services` → `ok()/fail()` 返回。**禁止在 endpoint 写业务逻辑。**
- `services/*.py` 放纯业务逻辑，函数式为主，不依赖 FastAPI 对象（只依赖 `settings` / 其他 service）。
- `schemas/requests.py` 放跨端点复用的请求体；端点私有的 `*Request/*Body` 可定义在端点文件内（如 `feedback.py::FeedbackRequest`）。
- `core/` 放横切能力：`responses`（信封）、`exceptions`（错误码）、`rbac`（认证鉴权）、`user_context`（ContextVar）、`middleware`（trace）。

## 2. 文件头中文 docstring（每个新文件必须写）
说明职责 + 核心链路 + 对齐的文档章节，例如：

```python
"""RAG 检索链（在线问答侧，对齐企业级 RAG 文档第三 / 四节）

链路：Query → 双路召回（向量语义 + 关键词）→ RRF 融合 → bge-reranker 重排
       → 治理双阶段过滤 → 多样性裁剪 → 阈值拒答
"""
```

## 3. 类型注解（必须全覆盖）
- 用 PEP 604 写法：`str | None`、`list[dict]`、`dict | None`，不用 `Optional[]`。
- 公共函数必须注解参数与返回值；内部小函数至少注解关键参数。

## 4. 分节注释
大文件按 `# ---------------- 标题 ----------------` 分节，每节职责单一（参考 `rag.py`：惰性单例 / 写入删除 / 召回两路 / 融合重排 / 完整检索链）。

## 5. 统一响应信封（禁止裸返回）
```python
from app.core.responses import ok, fail
from app.core.exceptions import ErrorCode

return ok({"items": items}, "批量导入任务已提交")
return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
return fail(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
```
- 成功一律 `ok(data, msg)`；失败一律 `fail(ErrorCode.*, 中文msg, http_status)`，`trace_id` 由框架自动带。
- 错误码分段（`core/exceptions.py::ErrorCode`）：`1xxx` 通用 / `2xxx` RAG 对话（含 `2001` 拒答 / `2002` 限流）/ `3xxx` 户型 Skill / `4xxx` 任务 / `5xxx` 系统。**新增错误码必须落到对应号段。**
- 面向用户的 `msg` 必须中文、可操作（如"内容与当前版本一致（SHA256 相同），已跳过重复入库"）。

## 6. 认证鉴权与用户隔离（安全红线）
- 路由级登录：`include_router(x.router, dependencies=[Depends(get_current_user)])`（见 `api/v1/router.py`）；敏感端点再加 `Depends(require_perm("kb"))`。
- **绝不信任请求体里的 `tenant_id/user_id` 做权限判断**：可见范围一律 `governance.access_context()`（从 Token 的 ContextVar 推导）。记忆/检索的读写键必须是 `(tenant, Token用户名, thread)` 同一口径。
- 需要当前用户的 service 层代码用 `current_user()`（`core/user_context.py`），由 `get_current_user`（async，请求 task 内）写入。

## 7. 配置与常量
- 全部可调参数进 `app/config.py::Settings`（`.env` 可覆盖），**禁止硬编码 URL / 密钥 / 模型名 / 阈值**。
- 热更参数走 `settings.py` 的 `_HOT_FIELDS` + 落盘模式；向量/关键词后端切换走适配层（`vector_store` / `keyword_store`），**业务代码不直连具体库**，不可用时自动回退并 `status()` 可见。

## 8. 并发与长任务
- 阻塞 IO（模型推理、文件解析、Chroma）用 `asyncio.to_thread` 或 `BackgroundTasks`，**禁止在 async 函数里直接调阻塞库**。
- 惰性单例必须加锁双检（如 `rag.py::_embed_model` + `_meta_lock`）；模型下载前先 `os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)`。
- 模型/外部服务不可用 → 走演示或片段摘要降级，**绝不 500**（参考 `chat.py::_demo_stream` 与 LLM 中断兜底）。

## 9. 可观测与审计
- 问答/任务等关键链路必须 `_record()` → `observability.record()`（耗时 / 召回 / 拦截 / token 成本 / trace_id）。
- SSE 事件名固定：`source / phase / message / done(/progress/complete/error 任务类）`，`done` 载荷含 `references + guard + faithfulness + trace_id`。

## 10. 测试脚本风格（`backend/tests/smoke_*.py`）
- 文件头 docstring 写清覆盖点 + 用法：`python tests/smoke_x.py [http://127.0.0.1:8010]`。
- Windows 控制台先 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
- `httpx.Client(timeout=..., trust_env=False)`，先 `POST /auth/login` 取 token 组 `Authorization` 头。
- 输出 `PASS/FAIL` 明细 + `RESULT: N passed, M failed`；进程退出码反映成败。

## 11. 修改后必跑
`python -m py_compile <改动文件>`；涉及接口改 `openapi.json` 自查；跑对应 `tests/smoke_*.py`。
