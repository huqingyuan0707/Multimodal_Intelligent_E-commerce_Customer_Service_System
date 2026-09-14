// 坐席工作台接口层（FR-7 转人工闭环：队列 / 流转 / 代回 / 内部备注 / 坐席 Trace）
// 对齐 API 规范 §4.11 + 页面设计 §3.2；JSON 走 request 自动解包，写操作一律带幂等键，id 走 encodeURIComponent。
import { request } from './http';

// 队列行：后端 handoff_to_dict（session 基础字段 + 流转态 + 最新消息预览）
export type WorkbenchRow = {
  id: string;
  title: string;
  username: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  handoff_status: string;
  handoff_label: string;
  assignee: string;
  handoff_reason: string;
  resolution: string;
  last_message: string;
};

export type WorkbenchPage = {
  items: WorkbenchRow[];
  total: number;
  page: number;
  size: number;
};

// 内部备注（仅坐席可见，买家侧不可见）
export type WorkbenchNote = {
  id: string;
  session_id: string;
  author: string;
  content: string;
  created_at: string;
};

// 上下文用量（后端 context_service 口径，坐席用于判断摘要/裁剪是否发生）
export type WorkbenchContext = {
  summary: string;
  rounds: number;
  tokens: number;
  dropped: number;
  budget: number;
  window_rounds: number;
};

// 坐席 Trace：会话流转态 + 消息（含引用/trace_id）+ 上下文用量，与买家侧同源
export type WorkbenchTrace = {
  session: WorkbenchRow;
  messages: unknown[];
  context: WorkbenchContext;
};

// 队列查询：status 空/open=待接+处理中，pending/handling/resolved/none 精确过滤；q 搜标题/买家
export type WorkbenchQueueQuery = {
  status?: string;
  q?: string;
  page?: number;
  size?: number;
};

export const queueWorkbenchApi = (params: WorkbenchQueueQuery = {}) =>
  request({
    method: 'GET',
    path: '/api/v1/workbench/queue',
    params: {
      status: params.status ?? '',
      q: params.q ?? '',
      page: params.page ?? 1,
      size: params.size ?? 20,
    },
  });

// 转人工：常驻买家侧「转人工」入口，none/resolved→pending（解决后可重开）
export const handoffWorkbenchApi = (params: { id: string; reason?: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/handoff`,
    params: { reason: params.reason ?? '' },
    idempotent: true,
  });

// 抢接：pending/none→handling + assignee=本人；已被他人认领返回 1001（前端转只读围观）
export const claimWorkbenchApi = (params: { id: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/claim`,
    params: {},
    idempotent: true,
  });

// 转接：assignee 必填，pending 顺手进入 handling
export const transferWorkbenchApi = (params: { id: string; assignee: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/transfer`,
    params: { assignee: params.assignee },
    idempotent: true,
  });

// 解决归档：handling/pending→resolved + 解决小结
export const resolveWorkbenchApi = (params: { id: string; conclusion?: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/resolve`,
    params: { conclusion: params.conclusion ?? '' },
    idempotent: true,
  });

// 坐席代回：仅 handling 会话可发，落 agent 行买家可见（返回消息含 trace_id）
export const replyWorkbenchApi = (params: { id: string; content: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/reply`,
    params: { content: params.content },
    idempotent: true,
  });

// 内部备注列表
export const listNotesWorkbenchApi = (params: { id: string }) =>
  request({
    method: 'GET',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/notes`,
  });

// 新增内部备注
export const addNoteWorkbenchApi = (params: { id: string; content: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/notes`,
    params: { content: params.content },
    idempotent: true,
  });

// 坐席 Trace 详情
export const traceWorkbenchApi = (params: { id: string; size?: number }) =>
  request({
    method: 'GET',
    path: `/api/v1/workbench/sessions/${encodeURIComponent(params.id)}/trace`,
    params: { size: params.size ?? 50 },
  });
