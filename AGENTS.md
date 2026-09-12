# AGENTS.md — 本项目唯一执行入口（人 + AI 都认它）

> 文档正文不复制，只索引。写代码前必读本文件 + 对应 Skill + 对应规范章节。偏离就停下说明，不猜。

## 1. 文档索引（Single Source of Truth）

| 改什么 | 先读什么（按顺序） |
|---|---|
| 需求/验收口径 | `多模态智能电商客服系统需求文档-FRDv2.md` |
| 架构/分层/选型 | `电商开发文档.md`、`后端工程化.md`、`前端工程化.md`、`部署工程化.md` |
| 页面/组件/路由 | `页面设计.md` §1 路由表、§3 页面详设、§7 组件清单 |
| 接口/SSE/错误码 | `API接口与SSE事件协议规范.md`（信封 `ok/fail`、ErrorCode 1xxx-5xxx、SSE `source/phase/message/done`） |
| 表/键/存储 | `数据模型与存储设计.md`（PG DDL、Redis 键、S3 布局） |
| RAG 链路 | `RAG知识库构建检索治理规范.md`（双路召回→RRF→重排→治理过滤→拒答 2001） |
| 测试/门禁 | `测试评估验收方案.md` §2-§4、§7 CI 示例 |
| 后端风格 | `skills/backend-code-style/SKILL.md` |
| 前端风格 | `skills/frontend-code-style/SKILL.md` |

## 2. AI 工作流（强制）

1. 用 `skill` 工具加载对应风格 Skill；用 `read` 打开上面表格里的一行规范，不凭记忆写。
2. 回复开头声明一行：`对齐文档：<文件名> §<节> + Skill §<节>`。
3. 新文件必须写中文文件头 docstring（职责 + 链路 + 对齐章节），见后端 Skill §2。
4. 改接口必须同步改 `API接口与SSE事件协议规范.md` + 自查 `openapi.json`；改 RAG 同步 RAG 规范；改页面同步 `页面设计.md`。
5. 贴验证命令输出，不说“应该过了”。

## 3. 后端红线（FastAPI）

- 分层：`endpoints/*.py` 薄封装（解析→调 service→`ok()/fail()`），业务进 `services/` 纯函数，不依赖 FastAPI 对象。私有 `*Request` 可放端点文件内。
- 类型：PEP 604（`str | None`），公共函数全注解；Ruff `UP` 规则已强制。
- 信封：成功 `ok(data, 中文msg)`，失败 `fail(ErrorCode.*, 中文可操作msg, http)`，`trace_id` 框架带。新增错误码落号段：1xxx 通用 / 2xxx 对话（2001 拒答 / 2002 限流）/ 3xxx 业务 / 4xxx 任务 / 5xxx 系统。
- 安全：路由级 `Depends(get_current_user)`，敏感加 `Depends(require_perm(...))`；**绝不信任请求体 `tenant_id/user_id`**，一律 `governance.access_context()` + service 用 `current_user()`；记忆/检索键 `(tenant, Token用户名, thread)` 同一口径。
- 配置：可调全进 `app/config.py::Settings`，热更走 `_HOT_FIELDS`；向量/关键词走适配层，业务不直连具体库，不可用回退且 `status()` 可见。
- 并发：阻塞 IO（模型/解析/Chroma）走 `asyncio.to_thread` 或 `BackgroundTasks`；惰性单例双检锁；模型下载前 `setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)`；模型挂了走演示/摘要降级，**绝不 500**。
- 可观测：关键链路 `_record() → observability.record()`；SSE 事件名 `source/phase/message/done（任务类 +progress/complete/error）`，`done` 含 `references+guard+faithfulness+trace_id`。
- 验证：`python -m py_compile <改动文件>`；`ruff check .`；`mypy app`；`pytest`；对应 `tests/smoke_*.py`（头 docstring + `utf-8 reconfigure` + `httpx(trust_env=False)` + 先 login 取 token + `PASS/FAIL` + `RESULT` + 退出码）。

## 4. 前端红线（Vue3 + TS + Element Plus）

- 基线：`pnpm`，`<script setup lang="ts">`，`@`= `src/`，Prettier（semi/singleQuote/2/printWidth 100/arrowParens avoid/lf），`pnpm lint` 0 errors。
- **页面方法一律箭头函数**（`func-style: expression` 硬拦截）：`const loadDocs = async () => {}`，先定义后调用；禁 `function foo(){}`。
- 目录：新业务 `src/features/<domain>/{api,components,composables,stores,types,views}`，存量 `src/views` 只修不扩；Agent 类型先行 `features/agent/types/agent.ts`。
- API 唯一入口 `src/api/index.ts`：JSON 走 `request<T>`（自动解包，`code!==0` 抛错）；上传 FormData 不手设 Content-Type；SSE fetch 必带 `Authorization`；GET 参数 `encodeURIComponent`；页面禁直写 `fetch`（ESLint 已拦，仅 `src/api` /测试/配置豁免）。
- 状态：Pinia setup 风格按域拆；逻辑抽 `composables/useXxx`；SSE 按 `event:/data:` 分帧→`phase/message/done` 分支，`done` 的 `JSON.parse` 必 try/catch。
- UI：优先 `AiButton/AiInput`；按需引入；样式用 `var(--reai-*)` + `scoped`；成功/失败 `ElMessage`，破坏操作先 `ElMessageBox.confirm`；枚举走映射表（如 `LEVEL_TAG`）；文案注释中文。
- 数据：`onMounted` 调真接口，`catch` 回退 `@/mock`；新会话本地 `t-${Date.now()}` 占位；切会话优先 `api.getSession(id)`，404 回退 mock。
- 401（HTTP 或业务码 `1002`）走中央 `handle401()`，禁页面自跳。
- 验证：`pnpm lint` + `pnpm typecheck` + `pnpm build`；改 store/composable 加 `vitest`（`src/**/*.test.ts`）；提交走 commitlint（feat/fix/docs/style/refactor/perf/test/chore/revert/build/ci + sentence-case ≤100）。

## 5. 联动规则

- 后端改路由/schema/错误码 → 同 PR 改 API 规范 + `openapi.json` 自查说明。
- 改 RAG（切分/召回/阈值/密级）→ 同 PR 改 RAG 规范 + 检索测试截图/输出。
- 改页面/组件/路由权限 → 同 PR 改 `页面设计.md` 对应节 + 埋点说明。
- 改表/键/存储 → 同 PR 改数据模型文档 + Alembic 说明（先加字段后发代码再删旧字段）。
- 选型变更先写 ADR（见 `ADR规范与模板.md`），不直接改代码。

## 6. 命令速查

```bash
# 后端（backend/）
python -m py_compile <改动文件>
ruff check . ; ruff format --check .
mypy app
pytest --cov=app --cov-report=term-missing
python tests/smoke_x.py [http://127.0.0.1:8010]

# 前端（frontend/）
pnpm lint ; pnpm typecheck ; pnpm build
pnpm test
```

CI（`.github/workflows/ci.yml`）与本地 `lint-staged + husky` 任一红灯不合并；`docs-guard` 检查接口与文档是否同改。
