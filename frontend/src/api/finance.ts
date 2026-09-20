// 对账结算接口（日结单列表 + 日结确认；对齐 API 规范 §4.7 财务节 / 页面设计 §3.14）
// 金额一律分；expected/diff/diff_warn 与告警阈值 diff_warn_cents 均由服务端下发，前端不做金额口径硬编码。
import { dispatch, type Envelope } from './http';

const check = (res: Envelope) => {
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 日结单分页列表（biz_date 精确筛选；行含 diff_warn 红字标记与 unsettled 待结算数）
export const listBillsApi = async (params?: { biz_date?: string; page?: number; size?: number }) =>
  check(
    await dispatch({
      path: '/api/v1/finance/bills',
      params: {
        biz_date: params?.biz_date ?? '',
        page: params?.page ?? 1,
        size: params?.size ?? 20,
      },
    }),
  );

// 日结制单（第一步，落制单人；重复制单 1001；对齐 API 规范 §4.7 双人复核两步）
export const settleBillApi = async (params: { biz_date: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: '/api/v1/finance/settle',
      params: { biz_date: params.biz_date },
      idempotent: true,
    }),
  );

// 日结复核（第二步，换人复核通过才置已结算；同账号自审自复后端 1001 兜底）
export const confirmSettleBillApi = async (params: { biz_date: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: '/api/v1/finance/settle/confirm',
      params: { biz_date: params.biz_date },
      idempotent: true,
    }),
  );
