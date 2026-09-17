// 管理后台类型先行（租户/用户/配额/审计，字段口径对齐后端 admin_service；对齐页面设计 §3.8）
export type TenantItem = {
  id: string;
  code: string;
  name: string;
  plan: string;
  plan_label: string;
  status: string;
  status_label: string;
  quota_tokens: number;
  quota_concurrency: number;
  note: string;
  created_at: string;
};

export type AdminUserItem = {
  id: string;
  tenant: string;
  username: string;
  roles: string[];
  status: string;
  status_label: string;
  created_at: string;
};

export type AuditItem = {
  id: string;
  tenant: string;
  actor: string;
  action: string;
  target: string;
  detail: object;
  created_at: string;
};

export type AdminOverview = {
  tenant_total: number;
  user_total: number;
  suspended: number;
  audit_total: number;
};

// 枚举中文化映射表（模板禁止散落字面量，对齐 Skill §5）
export const PLAN_TAG = {
  trial: 'info',
  basic: 'primary',
  pro: 'success',
  enterprise: 'warning',
} as const;

export const TENANT_STATUS_TAG = {
  active: 'success',
  suspended: 'danger',
  disabled: 'info',
} as const;

export const tenantPlanTagOf = (plan: string) => PLAN_TAG[plan as keyof typeof PLAN_TAG] ?? 'info';

export const tenantStatusTagOf = (status: string) =>
  TENANT_STATUS_TAG[status as keyof typeof TENANT_STATUS_TAG] ?? 'info';

// ---------------- 密钥（FR-8「密钥（只显掩码）」） ----------------
// 后端结构上不回明文与摘要：这里的字段天生只有掩码，前端不要试图拼出完整口令。

export type AdminApiKeyItem = {
  id: string;
  tenant: string;
  name: string;
  prefix: string;
  masked: string;
  scopes: string[];
  status: string;
  status_label: string;
  expired: boolean;
  last_used_at: string;
  expires_at: string;
  rotated_at: string;
  created_at: string;
};

export type ApiKeyCreated = { item: AdminApiKeyItem; plaintext: string };

export const API_KEY_STATUS_TAG = {
  active: 'success',
  disabled: 'info',
} as const;

export const apiKeyStatusTagOf = (status: string) =>
  API_KEY_STATUS_TAG[status as keyof typeof API_KEY_STATUS_TAG] ?? 'info';

export const USER_STATUS_TAG = {
  active: 'success',
  frozen: 'danger',
} as const;

export const userStatusTagOf = (status: string) =>
  USER_STATUS_TAG[status as keyof typeof USER_STATUS_TAG] ?? 'info';

// ---------------- SLO 告警（FR-8「SLO 告警」） ----------------
// 值的来源层级是「本实例进程级聚合」（含全部租户），后端用 metric_scope/scope_note 标注，
// 前端必须把 note 展示出来，不能读成「本租户 SLO」。

export type SloMetricItem = {
  metric: string;
  label: string;
  unit: string;
  operator: string;
  threshold: number;
  current: number | null;
};

export type SloRuleItem = {
  id: string;
  tenant: string;
  metric: string;
  metric_label: string;
  unit: string;
  operator: string;
  threshold: number;
  window: string;
  enabled: boolean;
  note: string;
  current: number | null;
  no_data: boolean;
  breach: boolean;
  created_at: string;
  updated_at: string;
};

export type SloRuleList = {
  items: SloRuleItem[];
  total: number;
  page: number;
  size: number;
  metric_scope: string;
  scope_note: string;
  windows: string[];
};

export const SLO_UNIT_LABEL = {
  ratio: '比例',
  seconds: '秒',
  count: '次',
} as const;

export const SLO_OPERATOR_LABEL = {
  gte: '不低于',
  lte: '不高于',
} as const;

export const sloUnitLabelOf = (unit: string) =>
  SLO_UNIT_LABEL[unit as keyof typeof SLO_UNIT_LABEL] ?? unit;

export const sloOperatorLabelOf = (op: string) =>
  SLO_OPERATOR_LABEL[op as keyof typeof SLO_OPERATOR_LABEL] ?? op;

// 值的展示口径：比率标 %、秒带单位、缺数据显示「—」（与后端 no_data 语义一致）
export const formatSloValue = (value: number | null, unit: string) => {
  if (value === null || value === undefined) {
    return '—';
  }
  if (unit === 'ratio') {
    return `${(value * 100).toFixed(2)}%`;
  }
  if (unit === 'seconds') {
    return `${value} 秒`;
  }
  return `${value} 次`;
};

// ---------------- 消息模板与到达率（FR-12.2） ----------------

export type MessageTemplateItem = {
  id: string;
  tenant: string;
  name: string;
  channel: string;
  channel_label: string;
  content: string;
  status: string;
  status_label: string;
  sent: number;
  failed: number;
  delivered: number;
  reach_rate: number | null;
  no_data: boolean;
  created_at: string;
  updated_at: string;
};

export type ReachItem = {
  template: string;
  channel: string;
  channel_label: string;
  status: string;
  sent: number;
  failed: number;
  reach_rate: number | null;
  no_data: boolean;
};

export type ReachReport = {
  items: ReachItem[];
  total_sent: number;
  total_failed: number;
  total_delivered: number;
  reach_rate: number | null;
  no_data: boolean;
  window_note: string;
  gateway_note: string;
};

export type NotifySendResult = {
  template: string;
  channel: string;
  channel_label: string;
  user_ref: string;
  content: string;
  delivered: boolean;
  degraded: boolean;
  reason: string;
  rate_limit: { limit: number; window_seconds: number };
};

export const TEMPLATE_STATUS_TAG = {
  draft: 'info',
  active: 'success',
  disabled: 'warning',
} as const;

export const templateStatusTagOf = (status: string) =>
  TEMPLATE_STATUS_TAG[status as keyof typeof TEMPLATE_STATUS_TAG] ?? 'info';

export const CHANNEL_OPTIONS = [
  { value: 'sms', label: '短信' },
  { value: 'wechat', label: '企微' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'email', label: '邮件' },
] as const;

// ---------------- 组织：排班 / 绩效（FR-12.4） ----------------

export type ShiftItem = {
  id: string;
  tenant: string;
  username: string;
  work_date: string;
  start_time: string;
  end_time: string;
  skill: string;
  skill_label: string;
  note: string;
  created_at: string;
};

export type SkillOption = { value: string; label: string };

export type PerformanceItem = {
  username: string;
  handled: number;
  resolved: number;
  resolve_rate: number | null;
  avg_score: number | null;
  scored_sessions: number;
  no_score: boolean;
};

export type PerformanceReport = {
  items: PerformanceItem[];
  total: number;
  page: number;
  size: number;
  privacy_note: string;
  scope_note: string;
};

// 绩效数值展示：缺数据一律「—」，不拿 0 冒充（与后端 no_score/no_data 口径一致）
export const formatRate = (value: number | null) =>
  value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`;
