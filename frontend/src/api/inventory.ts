// 库存接口（对齐 FRD FR-10.2：预警筛选/出入库流水/多仓/盘点/补货）
import { dispatch } from './http';

export const listInventoryApi = async (params: {
  keyword?: string;
  only_warn?: boolean;
  warehouse_id?: string;
  sku_id?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/inventory',
    params: { ...params, page: params.page ?? 1, size: params.size ?? 20 },
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

// 盘点提交：差异行进审批、账实一致免审（返回 checked/diff_count/approval_ids）
export const stocktakeApi = async (params: {
  lines: { warehouse_id: string; sku_id: string; counted: number }[];
  reason: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/inventory/stocktake',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 补货需求：低于安全线一键生成（恒进审批，批准后才入库）
export const replenishApi = async (params: { sku_id: string; qty: number; reason: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/inventory/replenish',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
