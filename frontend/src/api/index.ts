// API 唯一入口（页面禁直写 fetch，对齐前端 Skill §3 + API 规范 §1）
// JSON 走 request<T> 自动解包 {code,msg,data,trace_id}；上传 FormData 不手设头；
// SSE 用 streamChat（本文件内允许 fetch，必带 Authorization）；GET 参数调用方 encodeURIComponent。
import type { Reference } from '@/types/agent';
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
