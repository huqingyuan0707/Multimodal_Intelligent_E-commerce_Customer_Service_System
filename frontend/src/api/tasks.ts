// 任务中心接口（对齐 API 规范 §4.5；后端暂无列表接口，页面用本地任务盒+单查轮询）
import { dispatch } from './http';

export const createTaskApi = async (params: {
  type: string;
  payload?: object;
}) => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/tasks',
    params,
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const getTaskApi = async (params: {
  taskId: string;
}) => {
  const res = await dispatch({
    path: `/api/v1/tasks/${encodeURIComponent(params.taskId)}`,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
