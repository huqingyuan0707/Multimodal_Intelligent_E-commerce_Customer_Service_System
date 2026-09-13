// 物流接口（对齐 FRD FR-10.7：轨迹查询、异常登记联动售后）
import { dispatch } from './http';

export const listCompaniesApi = async () => {
  const res = await dispatch({ path: '/api/v1/logistics/companies' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const trackLogisticsApi = async (params: { trackingNo: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/logistics/track',
    params: { tracking_no: params.trackingNo },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const markExceptionApi = async (params: { logisticsId: string; kind: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/logistics/exceptions',
    params: { logistics_id: params.logisticsId, kind: params.kind },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
