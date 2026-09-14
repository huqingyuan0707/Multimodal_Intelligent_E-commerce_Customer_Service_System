// 任务中心类型（对齐 API 规范 §4.5：建任务→task_id→轮询；SSE progress/complete/error 预留）
export type TaskStatus = 'pending' | 'running' | 'done' | 'error';

export type TaskItem = {
  task_id: string;
  type: string;
  status: TaskStatus;
  progress: number;
  created_at: string;
  result?: unknown;
  error?: unknown;
};

export type CreateTaskInput = {
  type: string;
  payload?: object;
};

export const TASK_STATUS_TAG = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  error: '失败',
} as const;

export const TASK_TYPE_TAG = {
  reindex: '知识重建索引',
  import: '批量导入',
  eval: '离线评估',
} as const;
