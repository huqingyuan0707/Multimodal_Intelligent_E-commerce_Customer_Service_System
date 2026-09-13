// API 唯一入口（页面禁直写 fetch，对齐前端 Skill §3 + API 规范 §1）
// JSON 走 request<T> 自动解包 {code,msg,data,trace_id}；上传 FormData 不手设头；
// SSE 用 streamChat（本文件内允许 fetch，必带 Authorization）；GET 参数调用方 encodeURIComponent。
import type { ApprovalItem } from '@/types/approval';
import type { Reference } from '@/types/agent';
import type {
  AftersaleItem,
  GoodsItem,
  InventoryRow,
  MemberItem,
  OrderItem,
  PageResult,
  PromoItem,
  ReviewItem,
  TicketItem,
} from '@/types/shop';
import type { AppUser, LoginResult } from '@/types/user';

const BASE = import.meta.env.VITE_API_BASE ?? '';

type Envelope<T> = {
  code: number;
  msg: string;
  data: T;
  trace_id?: string;
};

// 401 中央处理（HTTP 401 或业务码 1002）：清登录态回登录页，禁止各页面自写跳转。
// 已在 /login 时只清态不跳转：否则登录失败会被整页刷新，错误提示一闪而过（幂等防回环）。
export const handle401 = (): void => {
  sessionStorage.removeItem('reai_token');
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
};

// authRedirect=false 供登录接口自身使用：失败时把错误抛给页面提示，不触发 handle401
export type RequestOptions = RequestInit & { authRedirect?: boolean };

const fail = (msg: string, code: number): Error => {
  const err = new Error(msg) as Error & { code: number };
  err.code = code;
  return err;
};

export const request = async <T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> => {
  const { authRedirect = true, ...init } = options;
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const isForm = init.body instanceof FormData;
  if (!isForm && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const token = sessionStorage.getItem('reai_token') ?? '';
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await window.fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    let msg = '未登录或登录已过期';
    try {
      const body = (await res.json()) as Envelope<T>;
      msg = body?.msg || msg;
    } catch {
      msg = '未登录或登录已过期';
    }
    if (authRedirect) {
      handle401();
    }
    throw fail(msg, 1002);
  }
  const json = (await res.json()) as Envelope<T>;
  if (json.code === 1002) {
    if (authRedirect) {
      handle401();
    }
    throw fail(json.msg || '未登录', json.code);
  }
  if (json.code !== 0) {
    throw fail(json.msg || '请求失败', json.code);
  }
  return json.data;
};

export const api = {
  listSessions: () => request<{ id: string; title: string }[]>('/api/v1/sessions'),
  getSession: (id: string) =>
    request<{ id: string; messages: unknown[] }>(`/api/v1/sessions/${encodeURIComponent(id)}`),
  // 登录失败（401/1002）不回跳登录页，交由 LoginView 弹错误提示
  login: (username: string, password: string) =>
    request<LoginResult>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
      authRedirect: false,
    }),
  logout: () => request<null>('/api/v1/auth/logout', { method: 'POST' }),
  me: () => request<AppUser>('/api/v1/auth/me'),
  // B端最小闭环（GET 参数 URLSearchParams 自动编码；后端未就绪时页面 catch 回 mock）
  listGoods: (params: { keyword?: string; status?: string; page?: number; size?: number }) => {
    const q = new URLSearchParams();
    if (params.keyword) {
      q.set('keyword', params.keyword);
    }
    if (params.status) {
      q.set('status', params.status);
    }
    q.set('page', String(params.page ?? 1));
    q.set('size', String(params.size ?? 20));
    return request<PageResult<GoodsItem>>(`/api/v1/goods?${q.toString()}`);
  },
  setGoodsStatus: (productId: string, status: string) =>
    request<unknown>(`/api/v1/goods/${encodeURIComponent(productId)}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status }),
    }),
  submitPriceChange: (skuId: string, newPrice: number, reason: string) =>
    request<unknown>(`/api/v1/goods/skus/${encodeURIComponent(skuId)}/price-change`, {
      method: 'POST',
      body: JSON.stringify({ new_price: newPrice, reason }),
    }),
  listInventory: (params: { only_warn?: boolean; page?: number; size?: number }) => {
    const q = new URLSearchParams();
    if (params.only_warn) {
      q.set('only_warn', 'true');
    }
    q.set('page', String(params.page ?? 1));
    q.set('size', String(params.size ?? 50));
    return request<PageResult<InventoryRow>>(`/api/v1/inventory?${q.toString()}`);
  },
  moveStock: (payload: {
    kind: string;
    warehouse_id: string;
    sku_id: string;
    delta: number;
    reason: string;
  }) =>
    request<unknown>('/api/v1/inventory/moves', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listOrders: (params: { status?: string; keyword?: string; page?: number; size?: number }) => {
    const q = new URLSearchParams();
    if (params.status) {
      q.set('status', params.status);
    }
    if (params.keyword) {
      q.set('keyword', params.keyword);
    }
    q.set('page', String(params.page ?? 1));
    q.set('size', String(params.size ?? 20));
    return request<PageResult<OrderItem>>(`/api/v1/orders?${q.toString()}`);
  },
  shipOrder: (orderId: string, company: string, trackingNo: string) =>
    request<unknown>(`/api/v1/orders/${encodeURIComponent(orderId)}/ship`, {
      method: 'POST',
      body: JSON.stringify({ company, tracking_no: trackingNo }),
    }),
  createAftersale: (payload: { order_id: string; reason: string; amount: number; trace_id: string }) =>
    request<unknown>('/api/v1/aftersales', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listAftersales: (limit = 50) =>
    request<AftersaleItem[]>(`/api/v1/aftersales?limit=${limit}`),
  // 营销与会员（发券幂等键走 Idempotency-Key 头；对齐 FRD 附录 D/API §4.8）
  listPromos: () => request<PromoItem[]>('/api/v1/promos'),
  createPromo: (payload: { name: string; budget: number; total?: number; per_user?: number }) =>
    request<PromoItem>('/api/v1/promos', { method: 'POST', body: JSON.stringify(payload) }),
  grantCoupon: (promoId: string, payload: { user_ref: string; order_ref?: string }, idemKey: string) =>
    request<unknown>(`/api/v1/promos/${encodeURIComponent(promoId)}/grant`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idemKey },
      body: JSON.stringify(payload),
    }),
  getMember: (userRef: string) =>
    request<MemberItem>(`/api/v1/members/${encodeURIComponent(userRef)}`),
  adjustPoints: (userRef: string, delta: number) =>
    request<MemberItem>(`/api/v1/members/${encodeURIComponent(userRef)}/points`, {
      method: 'POST',
      body: JSON.stringify({ delta }),
    }),
  // 物流（公司/单号查询/异常转售后；对齐 FRD FR-10.7）
  listCompanies: () => request<{ name: string }[]>('/api/v1/logistics/companies'),
  trackLogistics: (trackingNo: string) =>
    request<Record<string, unknown>>('/api/v1/logistics/track', {
      method: 'POST',
      body: JSON.stringify({ tracking_no: trackingNo }),
    }),
  markException: (logisticsId: string, kind: string) =>
    request<{ logistics: Record<string, unknown>; aftersale_id: string }>(
      '/api/v1/logistics/exceptions',
      { method: 'POST', body: JSON.stringify({ logistics_id: logisticsId, kind }) },
    ),
  // 评价与工单（差评建单 SLA 2h；对齐 FRD FR-10.8/FR-12.3）
  listReviews: (level = '') =>
    request<ReviewItem[]>(`/api/v1/reviews?level=${encodeURIComponent(level)}&limit=50`),
  replyReview: (id: string, reply: string) =>
    request<unknown>(`/api/v1/reviews/${encodeURIComponent(id)}/reply`, {
      method: 'POST',
      body: JSON.stringify({ reply }),
    }),
  createReviewTicket: (id: string, assignee = '') =>
    request<unknown>(`/api/v1/reviews/${encodeURIComponent(id)}/ticket`, {
      method: 'POST',
      body: JSON.stringify({ assignee }),
    }),
  listTickets: (status = '') =>
    request<TicketItem[]>(`/api/v1/tickets?status=${encodeURIComponent(status)}&limit=50`),
  transferTicket: (id: string, assignee: string) =>
    request<unknown>(`/api/v1/tickets/${encodeURIComponent(id)}/transfer`, {
      method: 'POST',
      body: JSON.stringify({ assignee }),
    }),
  closeTicket: (id: string, conclusion: string) =>
    request<unknown>(`/api/v1/tickets/${encodeURIComponent(id)}/close`, {
      method: 'POST',
      body: JSON.stringify({ conclusion }),
    }),
  // 审批（列表默认待办；批/驳走 approvals 真接口，对齐 FRD 附录 A）
  listApprovals: (status = 'pending') =>
    request<ApprovalItem[]>(`/api/v1/approvals?status=${encodeURIComponent(status)}&limit=50`),
  approveApproval: (id: string, modifiedArgs: Record<string, unknown>) =>
    request<unknown>(`/api/v1/approvals/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ modified_args: modifiedArgs }),
    }),
  rejectApproval: (id: string, reason: string) =>
    request<unknown>(`/api/v1/approvals/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  // 图片上传（FormData 不手设头；后端落盘未就绪，先走通压缩/预览/上传链路）
  uploadImage: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<{ doc_id: string; filename: string }>('/api/v1/documents/upload', {
      method: 'POST',
      body: fd,
    });
  },
};

export type DonePayload = {
  references: Reference[];
  guard: { pass: boolean };
  faithfulness: number;
  trace_id: string;
};

export type StreamHandlers = {
  onSource: (name: string) => void;
  onPhase: (name: string) => void;
  onMessage: (content: string) => void;
  onDone: (payload: DonePayload) => void;
  onError: (msg: string) => void;
};

const parseFrame = (frame: string, handlers: StreamHandlers): void => {
  const lines = frame.split('\n');
  const ev =
    lines
      .find(l => l.startsWith('event:'))
      ?.slice(7)
      .trim() ?? '';
  const data =
    lines
      .find(l => l.startsWith('data:'))
      ?.slice(5)
      .trim() ?? '';
  if (ev === 'source') {
    try {
      handlers.onSource((JSON.parse(data) as { name: string }).name);
    } catch {
      handlers.onSource(data);
    }
    return;
  }
  if (ev === 'phase') {
    try {
      handlers.onPhase((JSON.parse(data) as { name: string }).name);
    } catch {
      handlers.onPhase(data);
    }
    return;
  }
  if (ev === 'message') {
    try {
      handlers.onMessage((JSON.parse(data) as { content: string }).content);
    } catch {
      handlers.onMessage(data);
    }
    return;
  }
  if (ev === 'done') {
    try {
      handlers.onDone(JSON.parse(data) as DonePayload);
    } catch {
      handlers.onError('流式结束帧解析失败');
    }
  }
};

// SSE 对话（fetch 必带 Authorization，401 走中央 handle401；done 解析失败进 onError）
export const streamChat = async (
  query: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> => {
  const token = sessionStorage.getItem('reai_token') ?? '';
  let res: Response;
  try {
    res = await window.fetch(`${BASE}/api/v1/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ query }),
      signal,
    });
  } catch {
    handlers.onError('网络异常，请检查后端是否启动');
    return;
  }
  if (res.status === 401) {
    handle401();
    handlers.onError('未登录');
    return;
  }
  const reader = res.body?.getReader();
  if (!reader) {
    handlers.onError('浏览器不支持流式读取');
    return;
  }
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop() ?? '';
    frames.forEach(f => {
      if (f.trim()) {
        parseFrame(f, handlers);
      }
    });
  }
};

// 任务中心（对齐 API 规范 §4.5；后端暂无列表接口，页面用本地任务盒+单查轮询）
export const tasksApi = {
  create: (input: { type: string; payload?: Record<string, unknown> }) =>
    request<{ task_id: string }>('/api/v1/tasks', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  get: (taskId: string) =>
    request<{ task_id: string; status: string; progress: number }>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}`,
    ),
};

// 知识库（对齐 API 规范 §4.4；FormData 上传不手设头；删除/版本/检索测试后端暂无接口）
export const knowledgeApi = {
  list: () => request<unknown[]>('/api/v1/documents'),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<{ doc_id: string; filename?: string; skipped?: boolean }>(
      '/api/v1/documents/upload',
      { method: 'POST', body: fd },
    );
  },
  reindex: () => request<{ task_id: string }>('/api/v1/documents/reindex', { method: 'POST' }),
};
