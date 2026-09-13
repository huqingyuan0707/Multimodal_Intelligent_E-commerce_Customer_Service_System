// 库存接口（对齐 FRD FR-10.2：预警筛选/出入库流水/多仓）
import { dispatch } from './http';

export const listInventoryApi = async (params: {
  only_warn?: boolean;
  warehouse_id?: string;
  sku_id?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/inventory',
    params: { ...params, page: params.page ?? 1, size: params.size ?? 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const moveStockApi = async (params: {
  kind: string;
  warehouse_id: string;
  sku_id: string;
  delta: number;
  reason: string;
  to_warehouse_id?: string;
  order_ref?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/inventory/moves',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listWarehousesApi = async () => {
  const res = await dispatch({
    path: '/api/v1/inventory/warehouses',
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listMovesApi = async (params: { skuId?: string }) => {
  const res = await dispatch({
    path: '/api/v1/inventory/moves',
    params: { sku_id: params.skuId ?? '', limit: 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
