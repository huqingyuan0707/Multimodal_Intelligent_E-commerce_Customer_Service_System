// 风控复核接口（拦截复核：通过/拦截；对齐 API 规范 §4.8 风控节 / 页面设计 §3.18）
// 只落人工复核结论（reviewer+reason），禁全自动封号；拦截理由必填（1001），重复复核 3005。
import { dispatch, type Envelope } from './http';

const check = (res: Envelope) => {
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 风控事件分页列表（status/kind 精确筛选；行含 reviewable 供置灰，pending 为本页待复核数）
export const listRiskEventsApi = async (params?: {
  status?: string;
  kind?: string;
  page?: number;
  size?: number;
}) =>
  check(
    await dispatch({
      path: '/api/v1/risk/events',
      params: {
        status: params?.status ?? '',
        kind: params?.kind ?? '',
        page: params?.page ?? 1,
        size: params?.size ?? 20,
      },
    }),
  );

// 复核放行（仅待复核可处理；理由可空）
export const passRiskEventApi = async (params: { id: string; reason?: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: `/api/v1/risk/${encodeURIComponent(params.id)}/pass`,
      params: { reason: params.reason ?? '' },
      idempotent: true,
    }),
  );

// 复核拦截（理由必填，合规留痕；处置走人工流程）
export const blockRiskEventApi = async (params: { id: string; reason: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: `/api/v1/risk/${encodeURIComponent(params.id)}/block`,
      params: { reason: params.reason },
      idempotent: true,
    }),
  );
