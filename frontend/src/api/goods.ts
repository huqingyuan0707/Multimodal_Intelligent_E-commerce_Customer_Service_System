// 商品接口（B端最小闭环，对齐 FRD FR-10.1；后端不可用时页面置空并中文提示，不编造数据）
import { dispatch } from './http';

export const listGoodsApi = async (params: {
  keyword?: string;
  status?: string;
  page?: number;
  size?: number;
}) => {
  const res = await dispatch({
    path: '/api/v1/goods',
    params: { ...params, page: params.page ?? 1, size: params.size ?? 20 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const setGoodsStatusApi = async (params: { productId: string; status: string }) => {
  const res = await dispatch({
    method: 'PUT',
    path: `/api/v1/goods/${encodeURIComponent(params.productId)}/status`,
    params: { status: params.status },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const submitPriceChangeApi = async (params: {
  skuId: string;
  newPrice: number;
  reason: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/goods/skus/${encodeURIComponent(params.skuId)}/price-change`,
    params: { new_price: params.newPrice, reason: params.reason },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const updateSkuApi = async (params: { skuId: string; barcode?: string }) => {
  const res = await dispatch({
    method: 'PUT',
    path: `/api/v1/goods/skus/${encodeURIComponent(params.skuId)}`,
    params: { barcode: params.barcode },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
