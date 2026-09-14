// 审批接口（服务端分页默认 20 + 状态/类型/关键字筛选，对齐 API 规范 §4.5 + 页面设计 §3.4）
// 列表走服务端分页（后端 GET /approvals?page&size&status&action&keyword）；批/驳带 Idempotency-Key，后端复校验非法整体回滚。
import { dispatch } from './http';

// 后端分页对象兼容：新后端回 {items,total,page,size}，存量回数组时本地包装（联调过渡期不断前端）
const toPage = (raw: unknown, page: number, size: number) => {
  if (Array.isArray(raw)) {
    return { items: raw, total: raw.length, page, size };
  }
  const obj = (raw ?? {}) as { items?: unknown; total?: unknown; page?: unknown; size?: unknown };
  return {
    items: Array.isArray(obj.items) ? obj.items : [],
    total: typeof obj.total === 'number' ? obj.total : 0,
    page: typeof obj.page === 'number' ? obj.page : page,
    size: typeof obj.size === 'number' ? obj.size : size,
  };
};

export const listApprovalsApi = async (params?: {
  status?: string;
  action?: string;
  keyword?: string;
  page?: number;
  size?: number;
}) => {
  const page = params?.page ?? 1;
  const size = params?.size ?? 20;
  const res = await dispatch({
    path: '/api/v1/approvals',
    params: {
      status: params?.status ?? 'pending',
      action: params?.action ?? '',
      keyword: params?.keyword ?? '',
      page,
      size,
    },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return toPage(res.data, page, size);
};

export const approveApprovalApi = async (params: {
  id: string;
  modifiedArgs?: object;
  reason?: string;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: `/api/v1/approvals/${encodeURIComponent(params.id)}/approve`,
    params: { modified_args: params.modifiedArgs ?? {}, reason: params.reason ?? '' },
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const rejectApprovalApi = async (params: { id: string; reason: string }) => {
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

// 分页兼容：给 SearchFields/pageConfig + res.data.list/total 调用方用（服务端分页直通，老客户端裁剪已下线）
export const getApprovalListApi = async params => {
  const search = params?.SearchFields ?? {};
  const pageCfg = params?.pageConfig ?? {};
  const page = pageCfg.pageNum ?? params?.page ?? 1;
  const size = pageCfg.pageSize ?? params?.size ?? 20;
  const data = await listApprovalsApi({
    status: search.status ?? params?.status ?? 'pending',
    action: search.action ?? params?.action ?? '',
    keyword: search.keyword ?? params?.keyword ?? '',
    page,
    size,
  });
  return { code: 0, msg: '获取成功', data: { list: data.items, total: data.total } };
};
