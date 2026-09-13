// 数据看板类型先行（指标卡 + 按租户/渠道归因表；口径对齐页面设计 §3.7 + FRD FR-9）
// 链路：DashboardView → api/dashboard → 后端 /observability/summary（未就绪回 mock/dashboard）
export type MetricKey = 'qps' | 'p95' | 'resolve' | 'hallucination' | 'tool' | 'cost';

export type DashboardMetric = {
  key: MetricKey;
  label: string;
  value: string;
  desc: string;
  overBudget: boolean;
};

export type AttributionRow = {
  id: string;
  tenant: string;
  channel: string;
  sessions: number;
  resolveRate: string;
  costCents: number;
  overBudget: boolean;
  slowTraceId: string;
};

// 渠道中文化映射表（模板禁散落字面量，对齐前端 Skill §5）
export const CHANNEL_TAG = {
  taobao: '淘宝',
  doudian: '抖店',
  pdd: '拼多多',
  jd: '京东',
  widget: '独立站',
} as const;

export const channelLabelOf = (channel: string) =>
  CHANNEL_TAG[channel as keyof typeof CHANNEL_TAG] ?? channel;

// 金额分转元展示（后端金额字段一律分，页面禁裸展示分）
export const formatCost = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
