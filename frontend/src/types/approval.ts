// 审批类型先行（字段口径对齐后端 approval_service.to_dict，中文走 status_label/action_label；对齐页面设计 §3.4）
export type ApprovalItem = {
  id: string;
  action: string;
  action_label: string;
  target: string;
  args: object;
  reason: string;
  applicant: string;
  approver: string;
  status: string;
  status_label: string;
  session_id: string;
  created_at: string;
  decided_at: string;
  // 超时升级口径（后端 to_dict 必带，演示数据缺省按 false 处理）
  overdue?: boolean;
  waiting_hours?: number;
};

// 政策引用（详情抽屉行，点击跳知识库按标题筛选）
export type ApprovalPolicyRef = {
  id: string;
  title: string;
};

export type ApprovalDetail = ApprovalItem & {
  policy_refs: ApprovalPolicyRef[];
};

export type ApprovalPage = {
  items: ApprovalItem[];
  total: number;
  page: number;
  size: number;
};

// 未知状态兜底 info（后端加状态不断前端）
export const approvalTagOf = (status: string) => {
  const map = {
    pending: 'warning',
    approved: 'success',
    rejected: 'danger',
  } as const;
  return map[status as keyof typeof map] ?? 'info';
};

// 状态筛选（空=全部，后端 list_page 空串不过滤；默认待办）
export const APPROVAL_STATUS_OPTIONS = [
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
  { value: '', label: '全部' },
];

// 类型筛选（后端 action 精确匹配，空=全部；中文化走后端 action_label，前端只透传）
export const APPROVAL_ACTION_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'sku.price_change', label: 'SKU 改价' },
  { value: 'inventory.stocktake_diff', label: '盘点差异' },
  { value: 'inventory.replenish', label: '补货需求' },
  { value: 'order.refund', label: '退款' },
];

// 金额口径：退款 amount / 改价 new_price-old_price 均为分，转元展示（无金额返回空串）
export const approvalAmountOf = (item: ApprovalItem) => {
  const args = (item.args ?? {}) as { amount?: unknown; new_price?: unknown; old_price?: unknown };
  if (typeof args.amount === 'number') {
    return `￥${(args.amount / 100).toFixed(2)}`;
  }
  if (typeof args.new_price === 'number') {
    const old =
      typeof args.old_price === 'number' ? `￥${(args.old_price / 100).toFixed(2)} → ` : '';
    return `${old}￥${(args.new_price / 100).toFixed(2)}`;
  }
  return '';
};

// 证据图口径：售后 evidence[] 与建单入参同一口径（order_service.create_aftersale）
export const approvalEvidenceOf = (item: ApprovalItem) => {
  const args = (item.args ?? {}) as { evidence?: unknown };
  return Array.isArray(args.evidence) ? (args.evidence as string[]).filter(Boolean) : [];
};

// 已等待小时（创建时间距今，超时升级提示用；解析失败返回空串不断渲染）
export const approvalWaitingOf = (item: ApprovalItem) => {
  const ts = Date.parse((item.created_at ?? '').replace(' ', 'T'));
  if (Number.isNaN(ts)) {
    return '';
  }
  const hours = Math.max(0, (Date.now() - ts) / 3600000);
  if (hours < 1) {
    return `等待 ${Math.floor(hours * 60)} 分钟`;
  }
  return `等待 ${hours.toFixed(1)} 小时`;
};
