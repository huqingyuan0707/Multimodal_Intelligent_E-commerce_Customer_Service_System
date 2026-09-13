// 评价与工单接口（差评建单 SLA 2h；对齐 FRD FR-10.8/FR-12.3）
import { dispatch } from './http';

export const listReviewsApi = async (params?: { level?: string }) => {
  const res = await dispatch({
    path: '/api/v1/reviews',
    params: { level: params?.level ?? '', limit: 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const replyReviewApi = async (params: { id: string; reply: string }) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/reviews/${encodeURIComponent(params.id)}/reply`,
    params: { reply: params.reply },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const createReviewTicketApi = async (params: {
  id: string;
  assignee?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/reviews/${encodeURIComponent(params.id)}/ticket`,
    params: { assignee: params.assignee ?? '' },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listTicketsApi = async (params?: { status?: string }) => {
  const res = await dispatch({
    path: '/api/v1/tickets',
    params: { status: params?.status ?? '', limit: 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const transferTicketApi = async (params: {
  id: string;
  assignee: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/tickets/${encodeURIComponent(params.id)}/transfer`,
    params: { assignee: params.assignee },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const closeTicketApi = async (params: {
  id: string;
  conclusion: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/tickets/${encodeURIComponent(params.id)}/close`,
    params: { conclusion: params.conclusion },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
