// Agent Studio 接口层（Prompt 版本灰度回滚 + 工具试调 + 评测一键跑，对齐 API 规范 §4.13）
// JSON 走 request 自动解包（返回 data，调用方按 @/types/agent 断言）；写操作带幂等键；路径 id 走 encodeURIComponent。
import { request } from './http';

// Prompt 版本列表（线上置顶，其次更新倒序；服务端分页默认 20）
export const listPromptsApi = (params: { page?: number; size?: number } = {}) =>
  request({
    method: 'GET',
    path: '/api/v1/studio/prompts',
    params: { page: params.page ?? 1, size: params.size ?? 20 },
  });

// 新建草稿版本（版本号 vN 自动递增；正文空/超长后端 1001）
export const createPromptApi = (params: { desc: string; content: string }) =>
  request({
    method: 'POST',
    path: '/api/v1/studio/prompts',
    params: { desc: params.desc, content: params.content },
  });

// 发布版本（gray=100 全量需最近评测达验收线，否则后端 1001；其余进灰度）
export const publishPromptApi = (params: { version: string; gray: number }) =>
  request({
    method: 'POST',
    path: `/api/v1/studio/prompts/${encodeURIComponent(params.version)}/publish`,
    params: { gray: params.gray },
    idempotent: true,
  });

// 调整灰度中版本的放量比例（仅 gray 态可调）
export const setGrayPromptApi = (params: { version: string; gray: number }) =>
  request({
    method: 'POST',
    path: `/api/v1/studio/prompts/${encodeURIComponent(params.version)}/gray`,
    params: { gray: params.gray },
    idempotent: true,
  });

// 回滚（指定版本重上线上，原线上转归档；二次确认由页面承担）
export const rollbackPromptApi = (params: { version: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/studio/prompts/${encodeURIComponent(params.version)}/rollback`,
    params: {},
    idempotent: true,
  });

// 当前线上版本（无则 null；对话链 system prompt 取数口径同源）
export const onlinePromptApi = () =>
  request({ method: 'GET', path: '/api/v1/studio/prompts/online' });

// 工具清单（注册中心规格 + 熔断态；与 ToolCallCard 同源）
export const listToolsApi = () => request({ method: 'GET', path: '/api/v1/agent/tools' });

// 受控试调（Scope/参数/熔断由后端把关；敏感工具返回 approval_id，账不动）
export const invokeToolApi = (params: {
  name: string;
  args?: object;
  session_id?: string;
  trace_id?: string;
}) =>
  request({
    method: 'POST',
    path: `/api/v1/agent/tools/${encodeURIComponent(params.name)}/invoke`,
    params: {
      args: params.args ?? {},
      session_id: params.session_id ?? '',
      trace_id: params.trace_id ?? '',
    },
    idempotent: true,
  });

// 评测一键跑（建 run 即返；后台采样执行，轮询看 pending→done）
export const createEvalRunApi = (params: { name?: string; limit?: number } = {}) =>
  request({
    method: 'POST',
    path: '/api/v1/studio/evals',
    params: { name: params.name ?? 'default-200', limit: params.limit ?? 50 },
  });

// 评测历史（创建时间倒序；服务端分页默认 20）
export const listEvalRunsApi = (params: { page?: number; size?: number } = {}) =>
  request({
    method: 'GET',
    path: '/api/v1/studio/evals',
    params: { page: params.page ?? 1, size: params.size ?? 20 },
  });

// 评测 run 详情（含 score 双档 verdict + 分布 + misses）
export const getEvalRunApi = (params: { id: string }) =>
  request({
    method: 'GET',
    path: `/api/v1/studio/evals/${encodeURIComponent(params.id)}`,
  });
