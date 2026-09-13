// 审批类型先行（字段口径对齐后端 approval_service.to_dict，中文走 status_label/action_label；对齐页面设计 §3.4）
import type { TagColor } from '@/types/shop';

export type ApprovalItem = {
  id: string;
  action: string;
  action_label: string;
  target: string;
  args: Record<string, unknown>;
  reason: string;
  applicant: string;
  approver: string;
  status: string;
  status_label: string;
  session_id: string;
  created_at: string;
  decided_at: string;
};

// 未知状态兜底 info（后端加状态不断前端）
export const approvalTagOf = (status: string): TagColor => {
  const map: Record<string, TagColor> = {
    pending: 'warning',
    approved: 'success',
    rejected: 'danger',
  };
  return map[status] ?? 'info';
};
