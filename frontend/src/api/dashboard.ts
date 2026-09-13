// 数据看板接口（可观测聚合 + 治理巡检；对齐 API 规范 §4.6 + 页面设计 §3.7）
// 链路：DashboardView → 本文件 dispatch → 后端汇总；后端未就绪时页面回 mock 演示
import { dispatch } from './http';

export const getObservabilitySummaryApi = async () => {
  const res = await dispatch({ path: '/api/v1/observability/summary' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getGovernanceStatusApi = async () => {
  const res = await dispatch({ path: '/api/v1/governance/status' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listAttributionApi = async (params: { page?: number; size?: number }) => {
  const res = await dispatch({
    path: '/api/v1/observability/summary',
    params: { page: params.page ?? 1, size: params.size ?? 20 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
