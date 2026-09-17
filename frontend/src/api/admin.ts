// 管理后台接口（租户/配额/审计框架，对齐 API 规范 §4.9；分页默认 20，可切 10/20/50/100）
import { dispatch } from './http';

export const getAdminOverviewApi = async () => {
  const res = await dispatch({ path: '/api/v1/admin/overview' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listTenantsApi = async (params?: {
  keyword?: string;
  plan?: string;
  status?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/tenants',
    params: {
      keyword: params?.keyword ?? '',
      plan: params?.plan ?? '',
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

export const createTenantApi = async (params: {
  code: string;
  name: string;
  plan?: string;
  quota_tokens?: number;
  quota_concurrency?: number;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/admin/tenants',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const updateQuotaApi = async (params: {
  code: string;
  quota_tokens: number;
  quota_concurrency: number;
}) => {
  const res = await dispatch({
    method: 'PUT',
    path: `/api/v1/admin/tenants/${encodeURIComponent(params.code)}/quota`,
    params: {
      quota_tokens: params.quota_tokens,
      quota_concurrency: params.quota_concurrency,
    },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setTenantStatusApi = async (params: { code: string; status: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/admin/tenants/${encodeURIComponent(params.code)}/status`,
    params: { status: params.status },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listAdminUsersApi = async (params?: {
  tenant?: string;
  keyword?: string;
  status?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/users',
    params: {
      tenant: params?.tenant ?? '',
      keyword: params?.keyword ?? '',
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

export const updateUserRolesApi = async (params: { userId: string; roles: string }) => {
  const res = await dispatch({
    method: 'PUT',
    path: `/api/v1/admin/users/${encodeURIComponent(params.userId)}/roles`,
    params: { roles: params.roles },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listAuditsApi = async (params?: {
  tenant?: string;
  action?: string;
  keyword?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/admin/audits',
    params: {
      tenant: params?.tenant ?? '',
      action: params?.action ?? '',
      keyword: params?.keyword ?? '',
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
