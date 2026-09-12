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
| 3xxx | 户型/业务 Skill | 3001 ORDER_NOT_FOUND / 3002 ORDER_NOT_OWNED(越权) / 3003 REFUND_NEED_APPROVAL |
| 4xxx | 任务 | 4001 TASK_NOT_FOUND / 4002 TASK_TIMEOUT / 4003 APPROVAL_REQUIRED / 4004 APPROVAL_DENIED |
| 5xxx | 系统 | 5000 INTERNAL / 5001 UPSTREAM_FAILED / 5002 MODEL_UNAVAILABLE(走降级绝不500给用户) |

前端：HTTP401 或业务码 `1002` 一律走中央 `handle401()` 清登录态跳登录页，禁止各页面自写跳转。

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

前端：
- 401 中央处理；按钮级 `v-permission` + 路由 `meta.roles`；敏感操作先 `ElMessageBox.confirm`，结果 `ElMessage` 反馈。

## 4. REST 端点清单

### 4.1 认证
- `POST /auth/login {username,password}` → `ok({token, user:{name, perms}})`。前端存 `reai_token`。
- `GET /auth/me` → 当前用户 + 租户 + 权限。401 则 `handle401()`。

### 4.2 对话（非流式，调试/短问答）
- `POST /chat {query, thread_id?, security_level?}` → `ok({answer, references[], guard, faithfulness, trace_id})`。
- `2001` 表示无据拒答，前端渲染拒答话术 + 转人工按钮，不当错误抛异常。

### 4.3 会话与记忆
- `GET /sessions` → 列表；`POST /sessions {title?}` → 新会话（前端本地先建 `t-${Date.now()}` 占位，成功后以后端为准）。
- `GET /sessions/{id}` → 含消息；404 则回退 `@/mock` 演示数据，保证后端不可用时页面可用。
- `DELETE /sessions/{id}` → 需 confirm + 遗忘记忆键。

### 4.4 知识库
- `POST /documents/upload` FormData(`file`) → `ok({doc_id, sha256, skipped?})`，重复 SHA256 返回“已跳过重复入库”。
- `GET /documents` → 列表；`DELETE /documents/{id}` → 需 confirm；`POST /documents/reindex` → 异步任务 `{task_id}`。
- 上传失败 `fail(PARAM_INVALID,"请至少选择一个文件",400)`。

### 4.5 审批与任务
- `GET /approvals?status=pending` → 列表；`POST /approvals/{id}/approve {modified_args?}` / `POST /approvals/{id}/reject {reason}`。
- `POST /tasks {type, payload}` → `{task_id}`；`GET /tasks/{id}` → `{status, progress, result}`。SSE 任务类事件另含 `progress/complete/error`。

### 4.6 治理与可观测
- `GET /governance/status` → 向量/关键词后端可用性 + 阈值 + 热更字段。
- `GET /observability/summary` → 耗时/召回/拦截/token 成本聚合（后端 `_record() → observability.record()` 必埋）。

## 5. SSE 流式协议（项目实际形态）

后端事件名固定：`source / phase / message / done`（任务类另有 `progress/complete/error`）。`done` 载荷必含 `references + guard + faithfulness + trace_id`。

```python
"""聊天流 endpoint（对齐 API 规范 §5）"""
# app/api/v1/endpoints/chat.py
from fastapi.responses import StreamingResponse
from app.core.responses import ok  # 非流式用；流式按事件帧返回
import asyncio

async def _demo_stream(query: str):
    # 模型不可用时演示降级，绝不 500
    yield "event: message\ndata: {\"content\":\"演示模式：\"}\n\n"
    yield "event: done\ndata: {\"references\":[],\"guard\":{\"pass\":true},\"faithfulness\":1.0,\"trace_id\":\"demo\"}\n\n"

@router.post("/chat/stream")
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
`python -m py_compile <改动文件>`；接口改必 `openapi.json` 自查；跑对应 `tests/smoke_*.py`；前端 `pnpm lint`（0 errors）+ `pnpm typecheck` + `pnpm build`。CI 任一红灯不合并。
