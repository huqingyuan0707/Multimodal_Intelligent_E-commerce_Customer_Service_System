# PR 模板（不合规直接打回，无需争论）

## 对齐文档（必填，见 AGENTS.md §1）

- 对齐：`<文件名> §<节> + Skill §<节>`，例：`对齐文档：API接口与SSE事件协议规范.md §5 + backend Skill §5`
- 偏离说明（无则删）：___

## 改动类型

- [ ] 后端 / [ ] 前端 / [ ] 文档 / [ ] CI-部署
- [ ] 含接口变更 / [ ] 含 RAG 变更 / [ ] 含页面路由权限变更 / [ ] 含表键存储变更 / [ ] 含选型变更（ADR 编号：___）

## 联动文档（按 AGENTS.md §5 打勾）

- [ ] 接口-schema-错误码改 → 已同步 `API接口与SSE事件协议规范.md` + `openapi.json` 自查说明
- [ ] RAG 切分/召回/阈值/密级改 → 已同步 `RAG知识库构建检索治理规范.md` + 检索测试输出
- [ ] 页面/组件/路由权限改 → 已同步 `页面设计.md` 对应节 + 埋点说明
- [ ] 表/键/存储改 → 已同步 `数据模型与存储设计.md` + Alembic（先加字段后发代码再删旧字段）
- [ ] 无需同步（说明理由）：___

## 风格与安全自查

- 后端：endpoint 薄封装 + `ok()/fail()` + ErrorCode 号段 + PEP604 全注解 + `governance.access_context()`（禁信请求体 tenant）+ 阻塞走 `to_thread` + `_record()` 可观测 + SSE `source/phase/message/done` 且 done 含 `references+guard+faithfulness+trace_id`
- 前端：箭头函数 + `views/<domain>` 页面 + 顶层 `components/composables/stores/types` + 类型先行 + 唯一入口 `src/api/index.ts` + SSE 带 `Authorization` 且 done try/catch + `AiButton/AiInput` + `var(--reai-*)` + `ElMessage/confirm` + 401 走 `handle401()` + mock 降级（`t-${Date.now()}`/404 回退）
- 安全：鉴权 Scope + PII 脱敏 + 敏感先 confirm + 密钥不入库

## 验证（贴输出，不说“应该过了”）

```text
# 后端
python -m py_compile <文件> →
ruff check . →
mypy app →
pytest →
python tests/smoke_x.py → RESULT: N passed, M failed

# 前端
pnpm lint → 0 errors
pnpm typecheck →
pnpm build →
pnpm test →（改 store/composable 必有新增用例）
```

## 截图/录屏/Trace

- 页面改：附前后对比 + 埋点事件名
- 接口/SSE 改：附 `trace_id` + done 载荷
- 审计/成本影响：___
