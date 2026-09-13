// 审批接口（列表默认待办；批/驳走 approvals 真接口，对齐 FRD 附录 A）
import { dispatch } from './http';

export const listApprovalsApi = async (params?: { status?: string }) => {
  const res = await dispatch({
    path: '/api/v1/approvals',
    params: { status: params?.status ?? 'pending', limit: 50 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const approveApprovalApi = async (params: {
  id: string;
  modifiedArgs: object;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/approvals/${encodeURIComponent(params.id)}/approve`,
    params: { modified_args: params.modifiedArgs },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const rejectApprovalApi = async (params: {
  id: string;
  reason: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/approvals/${encodeURIComponent(params.id)}/reject`,
    params: { reason: params.reason },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 分页兼容：给 SearchFields/pageConfig + res.data.list/total 调用方用（类型宽松不写注解）
// 后端仍是 GET /approvals?status&limit，本函数做客户端分页裁剪，老 listApprovalsApi 不动
export const getApprovalListApi = async (params) => {
  const search = params?.SearchFields ?? {};
  const page = params?.pageConfig ?? {};
  const status = search.status ?? 'pending';
  const pageNum = page.pageNum ?? 1;
  const pageSize = page.pageSize ?? 20;
  const res = await dispatch({
    path: '/api/v1/approvals',
    params: { status, limit: 200 },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  const raw = res.data as any;
  const all = Array.isArray(raw) ? raw : (raw?.list ?? []);
  const total = Array.isArray(raw) ? raw.length : (raw?.total ?? all.length);
  const start = (pageNum - 1) * pageSize;
  const list = all.slice(start, start + pageSize);
  return { code: res.code, msg: res.msg, data: { list, total } };
};
