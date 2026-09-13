// SSE 流式对话（对齐 API 规范 §5：event source/phase/message/done；fetch 必带 Authorization，401 走中央 handle401）
import type { Reference } from '@/types/agent';
import { API_BASE, handle401 } from './http';

export type DonePayload = {
  references: Reference[];
  guard: { pass: boolean };
  faithfulness: number;
  trace_id: string;
};

export type StreamHandlers = {
  onSource: (name: string) => unknown;
  onPhase: (name: string) => unknown;
  onMessage: (content: string) => unknown;
  onDone: (payload: DonePayload) => unknown;
  onError: (msg: string) => unknown;
};

const parseFrame = (frame: string, handlers: StreamHandlers) => {
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

// SSE 对话（done 解析失败进 onError；网络异常提示检查后端）
export const streamChat = async (query: string, handlers: StreamHandlers, signal?: AbortSignal) => {
  const token = sessionStorage.getItem('reai_token') ?? '';
  let res: Response;
  try {
    res = await window.fetch(`${API_BASE}/api/v1/chat/stream`, {
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
