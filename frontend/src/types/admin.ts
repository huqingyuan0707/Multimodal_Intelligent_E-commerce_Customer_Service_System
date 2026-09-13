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

export const tenantPlanTagOf = (plan: string) =>
  PLAN_TAG[plan as keyof typeof PLAN_TAG] ?? 'info';

export const tenantStatusTagOf = (status: string) =>
  TENANT_STATUS_TAG[status as keyof typeof TENANT_STATUS_TAG] ?? 'info';
