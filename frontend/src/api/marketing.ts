// 营销与会员接口（发券幂等键走 Idempotency-Key 头；对齐 FRD 附录 D/API §4.8）
import { dispatch } from './http';

export const listPromosApi = async () => {
  const res = await dispatch({ path: '/api/v1/promos' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createPromoApi = async (params: {
  name: string;
  budget: number;
  total?: number;
  per_user?: number;
  valid_from?: string;
  valid_to?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/promos',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const grantCouponApi = async (params: {
  promoId: string;
  user_ref: string;
  order_ref?: string;
  idemKey: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/promos/${encodeURIComponent(params.promoId)}/grant`,
    params: { user_ref: params.user_ref, order_ref: params.order_ref },
    idempotent: true,
    idemKey: params.idemKey,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getMemberApi = async (params: { userRef: string }) => {
  const res = await dispatch({
    path: `/api/v1/members/${encodeURIComponent(params.userRef)}`,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const adjustPointsApi = async (params: { userRef: string; delta: number }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/members/${encodeURIComponent(params.userRef)}/points`,
    params: { delta: params.delta },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
