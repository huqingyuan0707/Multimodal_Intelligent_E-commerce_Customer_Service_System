// 管理后台扩展接口（密钥/SLO/消息/组织，对齐 API 规范 §4.9；与后端 admin_ops.py / admin_org.py 对应）
// 与 admin.ts（租户/配额/用户/审计）同域：拆文件只为守住单文件行数纪律，分页默认一律 20
import { dispatch } from './http';

// ---------------- 密钥（FR-8；明文仅创建/轮换响应返回一次） ----------------

export const listApiKeysApi = async (params?: {
  tenant?: string;
  status?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/api-keys',
    params: {
      tenant: params?.tenant ?? '',
      status: params?.status ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createApiKeyApi = async (params: {
  tenant: string;
  name: string;
  scopes?: string;
  expires_at?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/api-keys',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const rotateApiKeyApi = async (params: { keyId: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/api-keys/${encodeURIComponent(params.keyId)}/rotate`,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setApiKeyStatusApi = async (params: { keyId: string; status: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/api-keys/${encodeURIComponent(params.keyId)}/status`,
    params: { status: params.status },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// ---------------- SLO 告警（FR-8） ----------------

export const getSloMetricsApi = async () => {
  const res = await dispatch({ path: '/api/v1/admin/slo/metrics' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listSloRulesApi = async (params?: {
  tenant?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/slo/rules',
    params: {
      tenant: params?.tenant ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const saveSloRuleApi = async (params: {
  tenant: string;
  metric: string;
  operator: string;
  threshold: number;
  window?: string;
  enabled?: boolean;
  note?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/slo/rules',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setSloRuleEnabledApi = async (params: { ruleId: string; enabled: boolean }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/slo/rules/${encodeURIComponent(params.ruleId)}/enabled`,
    params: { enabled: params.enabled },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const deleteSloRuleApi = async (params: { ruleId: string }) => {
  const res = await dispatch({
    method: 'DELETE',
    path: `/api/v1/admin/slo/rules/${encodeURIComponent(params.ruleId)}`,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// ---------------- 消息模板与到达率（FR-12.2） ----------------

export const listTemplatesApi = async (params?: {
  tenant?: string;
  channel?: string;
  status?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/notify/templates',
    params: {
      tenant: params?.tenant ?? '',
      channel: params?.channel ?? '',
      status: params?.status ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createTemplateApi = async (params: {
  tenant: string;
  name: string;
  channel: string;
  content: string;
  status: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/notify/templates',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const updateTemplateApi = async (params: {
  templateId: string;
  name: string;
  channel: string;
  content: string;
  status: string;
}) => {
  const res = await dispatch({
    method: 'PUT',
    path: `/api/v1/admin/notify/templates/${encodeURIComponent(params.templateId)}`,
    params: {
      name: params.name,
      channel: params.channel,
      content: params.content,
      status: params.status,
    },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setTemplateStatusApi = async (params: { templateId: string; status: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/notify/templates/${encodeURIComponent(params.templateId)}/status`,
    params: { status: params.status },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const deleteTemplateApi = async (params: { templateId: string }) => {
  const res = await dispatch({
    method: 'DELETE',
    path: `/api/v1/admin/notify/templates/${encodeURIComponent(params.templateId)}`,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const sendNotifyApi = async (params: { tenant: string; name: string; user_ref: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/notify/send',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getReachApi = async (params?: { tenant?: string }) => {
  const res = await dispatch({
    path: '/api/v1/admin/notify/reach',
    params: { tenant: params?.tenant ?? '' },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// ---------------- 组织：排班 / 绩效 / 离职冻结（FR-12.4） ----------------

export const listShiftsApi = async (params?: {
  tenant?: string;
  username?: string;
  work_date?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/org/shifts',
    params: {
      tenant: params?.tenant ?? '',
      username: params?.username ?? '',
      work_date: params?.work_date ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createShiftApi = async (params: {
  tenant: string;
  username: string;
  work_date: string;
  start_time: string;
  end_time: string;
  skill: string;
  note?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/org/shifts',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const deleteShiftApi = async (params: { shiftId: string }) => {
  const res = await dispatch({
    method: 'DELETE',
    path: `/api/v1/admin/org/shifts/${encodeURIComponent(params.shiftId)}`,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getPerformanceApi = async (params?: {
  tenant?: string;
  username?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/org/performance',
    params: {
      tenant: params?.tenant ?? '',
      username: params?.username ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setUserFrozenApi = async (params: { userId: string; frozen: boolean }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/users/${encodeURIComponent(params.userId)}/status`,
    params: { frozen: params.frozen },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
