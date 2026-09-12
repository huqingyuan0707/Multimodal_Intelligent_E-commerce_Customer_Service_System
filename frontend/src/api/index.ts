// API 唯一入口（页面禁直写 fetch，对齐前端 Skill §3 + API 规范 §1）
// JSON 走 request<T> 自动解包 {code,msg,data,trace_id}；上传 FormData 不手设头；
// SSE 用 streamChat（本文件内允许 fetch，必带 Authorization）；GET 参数调用方 encodeURIComponent。
import type { Reference } from '@/types/agent';

const BASE = import.meta.env.VITE_API_BASE ?? '';

type Envelope<T> = {
  code: number;
  msg: string;
  data: T;
  trace_id?: string;
};

export const handle401 = (): void => {
  sessionStorage.removeItem('reai_token');
  window.location.href = '/login';
};

export const request = async <T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  const isForm = options.body instanceof FormData;
  if (!isForm && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const token = sessionStorage.getItem('reai_token') ?? '';
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await window.fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    handle401();
    throw new Error('未登录');
  }
  const json = (await res.json()) as Envelope<T>;
  if (json.code === 1002) {
    handle401();
    throw new Error(json.msg || '未登录');
  }
  if (json.code !== 0) {
    const err = new Error(json.msg || '请求失败') as Error & { code: number };
    err.code = json.code;
    throw err;
  }
  return json.data;
};

export const api = {
  listSessions: () => request<{ id: string; title: string }[]>('/api/v1/sessions'),
  getSession: (id: string) =>
    request<{ id: string; messages: unknown[] }>(
      `/api/v1/sessions/${encodeURIComponent(id)}`,
    ),
  login: (username: string, password: string) =>
    request<{ token: string; user: { name: string; tenant: string; roles: string[] } }>(
      '/api/v1/auth/login',
      { method: 'POST', body: JSON.stringify({ username, password }) },
    ),
  me: () =>
    request<{ name: string; tenant: string; roles: string[] }>('/api/v1/auth/me'),
};

export type DonePayload = {
  references: Reference[];
  guard: { pass: boolean };
  faithfulness: number;
  trace_id: string;
};

export type StreamHandlers = {
  onPhase: (name: string) => void;
  onMessage: (content: string) => void;
  onDone: (payload: DonePayload) => void;
  onError: (msg: string) => void;
};

const parseFrame = (frame: string, handlers: StreamHandlers): void => {
  const lines = frame.split('\n');
  const ev = lines.find((l) => l.startsWith('event:'))?.slice(7).trim() ?? '';
  const data = lines.find((l) => l.startsWith('data:'))?.slice(5).trim() ?? '';
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
    frames.forEach((f) => {
      if (f.trim()) {
        parseFrame(f, handlers);
      }
    });
  }
};
