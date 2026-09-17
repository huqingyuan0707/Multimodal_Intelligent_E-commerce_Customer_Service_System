// 订单与售后接口（对齐 FRD FR-10.3/FR-10.4：发货回填运单、签收完成、售后超额转审批、质检处置）
import { dispatch } from './http';

export const listOrdersApi = async (params: {
  status?: string;
  platform?: string;
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

export const getOrderDetailApi = async (orderId: string) => {
  const res = await dispatch({ path: `/api/v1/orders/${encodeURIComponent(orderId)}` });
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

export const confirmOrderApi = async (orderId: string) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/orders/${encodeURIComponent(orderId)}/confirm`,
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

// 售后质检处置：二次入库 / 报损（恒进审批）/ 退供
export const disposeAftersaleApi = async (params: {
  aftersaleId: string;
  disposition: 'restocked' | 'scrapped' | 'returned';
  warehouseId?: string;
  lines?: { sku_id: string; qty: number }[];
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/aftersales/${encodeURIComponent(params.aftersaleId)}/dispose`,
    params: {
      disposition: params.disposition,
      warehouse_id: params.warehouseId ?? '',
      lines: params.lines ?? [],
    },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 售后单服务端分页列表（前端红线：列表页必须服务端分页，默认 20 可切 10/20/50/100）
export const listAftersalesApi = async (params?: {
  status?: string;
  disposition?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/aftersales',
    params: {
      ...(params?.status ? { status: params.status } : {}),
      ...(params?.disposition ? { disposition: params.disposition } : {}),
      page: params?.page ?? 1,
      size: params?.size ?? 20,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
