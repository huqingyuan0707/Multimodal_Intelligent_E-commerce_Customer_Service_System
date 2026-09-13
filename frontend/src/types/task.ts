// 任务中心类型（对齐 API 规范 §4.5：建任务→task_id→轮询；SSE progress/complete/error 预留）
export type TaskStatus = 'pending' | 'running' | 'done' | 'error';

export type TaskItem = {
  task_id: string;
  type: string;
  status: TaskStatus;
  progress: number;
  created_at: string;
};

export type CreateTaskInput = {
  type: string;
  payload?: Record<string, unknown>;
};

export const TASK_STATUS_TAG: Record<TaskStatus, string> = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  error: '失败',
};
