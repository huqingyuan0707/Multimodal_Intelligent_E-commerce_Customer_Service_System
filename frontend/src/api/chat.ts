// SSE 流式对话（对齐 API 规范 §5：event source/phase/message/done；fetch 必带 Authorization，401 走中央 handle401）
import type { AgentMessage, Reference, SessionContext, VisionInspection } from '@/types/agent';
import { API_BASE, handle401 } from './http';

// 历史回放映射：后端 message_to_dict 行 → AgentMessage（引用/检测卡/trace 一次收口，页面只消费）
export const toAgentMessages = (list: unknown[]) => {
  if (!Array.isArray(list)) {
    return [];
  }
  return list.flatMap((m, i) => {
    if (typeof m !== 'object' || m === null) {
      return [];
    }
    // 后端行：content/role/modality/attachments/citations[{source,title,score}]/trace_id
    const r = m as {
      content?: string;
      role?: string;
      modality?: string;
      trace_id?: string;
      attachments?: VisionInspection[];
      citations?: { source?: string; title?: string; score?: number }[];
    };
    if (typeof r.content !== 'string') {
      return [];
    }
    const references = Array.isArray(r.citations)
      ? r.citations
          .filter(c => typeof c.title === 'string')
          .map(c => ({ source: c.source ?? '', title: c.title ?? '', score: c.score ?? 0 }))
      : [];
    const vision = Array.isArray(r.attachments)
      ? r.attachments.filter(v => typeof v.category === 'string')
      : [];
    return [
      {
        id: `h-${i}`,
        role: r.role === 'user' ? 'user' : 'agent',
        modality: r.modality === 'image' ? 'image' : 'text',
        content: r.content,
        references,
        trace_id: typeof r.trace_id === 'string' ? r.trace_id : undefined,
        vision: r.role === 'agent' ? vision : [],
        need_human: r.role === 'agent' && vision.some(v => v.need_human),
      } as AgentMessage,
    ];
  });
};

export type DonePayload = {
  references: Reference[];
  guard: { pass: boolean };
  faithfulness: number;
  trace_id: string;
  session_id: string;
  vision?: VisionInspection[];
  need_human?: boolean;
  context?: SessionContext;
};

export type StreamHandlers = {
  onSource: (name: string) => unknown;
  onPhase: (name: string) => unknown;
  onMessage: (content: string) => unknown;
  onDone: (payload: DonePayload) => unknown;
  onError: (msg: string) => unknown;
};

// 流式入参：threadId 复用后端会话（t- 开头本地占位不传），clientMsgId 幂等键（重连复用同一键不翻倍）
// 图文轮 imageIds/inspections 为上传步回执原样透传（后端清洗 + 阈值重算，不信任前端 need_human）
export type StreamOptions = {
  threadId?: string;
  clientMsgId?: string;
  imageIds?: string[];
  inspections?: VisionInspection[];
};

const parseFrame = (frame: string, handlers: StreamHandlers, seen: Set<string>) => {
  const lines = frame.split('\n');
  // 事件 id 行（后端全帧必带）：同流内重复 id 直接丢弃，保证幂等不重复拼接
  const id =
    lines
      .find(l => l.startsWith('id:'))
      ?.slice(3)
      .trim() ?? '';
  if (id) {
    if (seen.has(id)) {
      return;
    }
    seen.add(id);
  }
  const ev =
    lines
      .find(l => l.startsWith('event:'))
      ?.slice(7)
      .trim() ?? '';
  // data: 允许多行（SSE 规范），按换行拼接后再解析
  const data = lines
    .filter(l => l.startsWith('data:'))
    .map(l => l.slice(5).trim())
    .join('\n');
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
export const streamChat = async (
  query: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  opts?: StreamOptions,
) => {
  const token = sessionStorage.getItem('reai_token') ?? '';
  const seen = new Set<string>();
  let res: Response;
  try {
    res = await window.fetch(`${API_BASE}/api/v1/agent/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        query,
        thread_id: opts?.threadId,
        client_msg_id: opts?.clientMsgId ?? '',
        image_ids: opts?.imageIds ?? [],
        inspections: opts?.inspections ?? [],
      }),
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
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch {
      // 读流中段断开：主动停止静默返回，否则转可重连的错误（抛异常会卡死 streaming 状态）
      if (signal?.aborted) {
        return;
      }
      handlers.onError('连接中断，可重试');
      return;
    }
    const { done, value } = chunk;
    if (done) {
      break;
    }
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop() ?? '';
    frames.forEach(f => {
      if (f.trim()) {
        parseFrame(f, handlers, seen);
      }
    });
  }
};
