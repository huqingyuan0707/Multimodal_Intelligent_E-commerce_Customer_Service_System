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

// 工具调用记录（done.tool_calls 与 POST /agent/tools/{name}/invoke 出参同一形状，
// 对齐 API 规范 §4.12/§5 + FR-5「ToolCallCard 透明展示、可展开参果」）
// status：ok=已执行（approval_required 为真表示结果进审批闸门，账目未变动）/ rejected=业务拒绝（越权、参数、不存在）
export type ToolCall = {
  tool: string;
  status: 'ok' | 'rejected';
  scope?: string;
  idempotent?: boolean;
  requires_approval?: boolean;
  approval_required?: boolean;
  approval_id?: string;
  args?: object;
  result?: object;
  attempts?: number;
  latency_ms?: number;
  timeout_seconds?: number;
  code?: number;
  message?: string;
  trace_id?: string;
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
  // 本轮真调工具记录（ToolCallCard 透明展示）与编排说明（缺必填参数/无权调用/回落如实透出）
  tool_calls?: ToolCall[];
  notes?: string[];
  // 赞踩反馈定位键（done.message_id，POST /mining/feedback 入参；本地演示/占位行为空即不显按钮）
  message_id?: string;
  // 本轮反馈结果（'up' | 'down'，提交成功后置灰防重复）
  feedback?: 'up' | 'down';
  // 错误气泡（友好话术 + 重试 + 转人工，对齐页面设计 §3.1 状态完整性）
  retryable?: boolean;
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
