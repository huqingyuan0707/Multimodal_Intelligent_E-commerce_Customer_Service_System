// 任务中心接口（对齐 API 规范 §4.5；列表按本人隔离倒序，分页默认 20）
import { request } from './http';

export const createTaskApi = async (params: { type: string; payload?: object }) =>
  request({
    method: 'POST',
    path: '/api/v1/tasks',
    params,
    idempotent: true,
  });

export const listTasksApi = async (params?: { page?: number; size?: number; status?: string }) =>
  request({
    path: '/api/v1/tasks',
    params: {
      page: params?.page ?? 1,
      size: params?.size ?? 20,
      status: params?.status ?? '',
    },
  });

export const getTaskApi = async (params: { taskId: string }) =>
  request({
    path: `/api/v1/tasks/${encodeURIComponent(params.taskId)}`,
  });
