// 数据看板接口（可观测汇总；对齐 API 规范 §4.6 + 页面设计 §3.7）
// 链路：DashboardView → 本文件 dispatch → GET /observability/summary；失败由页面空态 + 中文提示
import { dispatch } from './http';
import type { AttributionRow, DashboardMetric } from '@/types/dashboard';

export type DashboardTrendPoint = {
  label: string;
  value: number;
};

export type DashboardSlowTrace = {
  trace_id: string;
  latency_ms: number;
  tool: string;
};

export type DashboardSummary = {
  metrics: DashboardMetric[];
  trend: DashboardTrendPoint[];
  slow_traces: DashboardSlowTrace[];
  items: AttributionRow[];
  total: number;
  page: number;
  size: number;
  range: string;
};

export const getDashboardSummaryApi = async (params: {
  page?: number;
  size?: number;
  range?: string;
}) => {
  const res = await dispatch({
    path: '/api/v1/observability/summary',
    params: { page: params.page ?? 1, size: params.size ?? 20, range: params.range ?? 'today' },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data as DashboardSummary;
};

export const getGovernanceStatusApi = async () => {
  const res = await dispatch({ path: '/api/v1/governance/status' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
