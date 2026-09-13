// 会话与鉴权接口（对齐 API 规范 §4.1/§4.3；登录失败不回跳，交由 LoginView 提示）
import { request } from './http';

export const listSessionsApi = async (params?: { page?: number; size?: number }) =>
  request({
    path: '/api/v1/sessions',
    params: { page: params?.page ?? 1, size: params?.size ?? 20 },
  });

export const createSessionApi = async (params?: { title?: string }) =>
  request({
    method: 'POST',
    path: '/api/v1/sessions',
    params: { title: params?.title ?? '新会话' },
  });

export const getSessionApi = async (params: { id: string }) =>
  request({
    path: `/api/v1/sessions/${encodeURIComponent(params.id)}`,
  });

export const deleteSessionApi = async (params: { id: string }) =>
  request({
    method: 'DELETE',
    path: `/api/v1/sessions/${encodeURIComponent(params.id)}`,
  });

export const loginApi = async (params: { username: string; password: string }) =>
  request({
    method: 'POST',
    path: '/api/v1/auth/login',
    params,
    authRedirect: false,
  });

export const logoutApi = async () =>
  request({ method: 'POST', path: '/api/v1/auth/logout' });

export const meApi = async () => request({ path: '/api/v1/auth/me' });
