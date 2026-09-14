// Agent 类型先行（禁止各文件自造消息形状，对齐前端 Skill §2 + API 规范 §5）
export type ChatRole = 'user' | 'agent';

export type Reference = {
  source: string;
  title: string;
  score: number;
};

export type VisionInspection = {
  category: string;
  confidence: number;
  desc: string;
  need_human: boolean;
  degraded: boolean;
};

export type AgentMessage = {
  id: string;
  role: ChatRole;
  modality: 'text' | 'image' | 'voice';
  content: string;
  references?: Reference[];
  trace_id?: string;
  vision?: VisionInspection[];
  need_human?: boolean;
  images?: string[];
  context?: SessionContext;
  // 追问延伸 chips（随最后一条 Agent 回复展示，点击直接发送，对齐页面设计 §3.1）
  followups?: string[];
};

export type AgentEvent =
  | { kind: 'source'; name: string }
  | { kind: 'phase'; name: string }
  | { kind: 'message'; content: string }
  | {
      kind: 'done';
      references: Reference[];
      trace_id: string;
    };

export type Session = {
  id: string;
  title: string;
  summary?: string;
  message_count?: number;
};

export type SessionContext = {
  rounds: number;
  tokens: number;
  dropped: number;
  summarized: boolean;
};

export const LEVEL_TAG = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
} as const;
