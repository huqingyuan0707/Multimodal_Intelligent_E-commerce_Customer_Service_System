// 会话与鉴权接口（对齐 API 规范 §4.1/§4.6；登录失败不回跳，交由 LoginView 提示）
import { dispatch } from './http';

export const listSessionsApi = async () => {
  const res = await dispatch({ path: '/api/v1/sessions' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getSessionApi = async (params: { id: string }) => {
  const res = await dispatch({
    path: `/api/v1/sessions/${encodeURIComponent(params.id)}`,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const loginApi = async (params: { username: string; password: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/auth/login',
    params,
    authRedirect: false,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const logoutApi = async () => {
  const res = await dispatch({ method: 'POST', path: '/api/v1/auth/logout' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const meApi = async () => {
  const res = await dispatch({ path: '/api/v1/auth/me' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
