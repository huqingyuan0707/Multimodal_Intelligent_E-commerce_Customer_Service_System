// 订单与售后接口（对齐 FRD FR-10.3/FR-10.4：发货回填运单、售后超额转审批）
import { dispatch } from './http';

export const listOrdersApi = async (params: {
  status?: string;
  keyword?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/orders',
    params: { ...params, page: params.page ?? 1, size: params.size ?? 20 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const shipOrderApi = async (params: {
  orderId: string;
  company: string;
  trackingNo: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/orders/${encodeURIComponent(params.orderId)}/ship`,
    params: { company: params.company, tracking_no: params.trackingNo },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createAftersaleApi = async (params: {
  order_id: string;
  reason: string;
  amount: number;
  trace_id: string;
  evidence?: string[];
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/aftersales',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listAftersalesApi = async (params?: { limit?: number }) => {
  const res = await dispatch({
    path: '/api/v1/aftersales',
    params: { limit: params?.limit ?? 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
