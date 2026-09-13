// 演示兜底数据（后端不可用时回退，对齐前端 Skill §6；口径见页面设计 §4）
import type { ApprovalItem } from '@/types/approval';
import type { GoodsItem, InventoryRow, OrderItem } from '@/types/shop';

export type MockSession = {
  id: string;
  title: string;
};

export const mockSessions: MockSession[] = [
  { id: 't-demo-1', title: '演示会话：退换咨询' },
  { id: 't-demo-2', title: '演示会话：尺码推荐' },
];

// 工作台演示数据（后端队列/画像接口就绪前占位，口径见页面设计 §3.2）
export type MockWorkSession = {
  id: string;
  name: string;
  tag: string;
  vip?: boolean;
};

export const mockWorkSessions: MockWorkSession[] = [
  { id: 'w-1', name: '王女士', tag: 'VIP', vip: true },
  { id: 'w-2', name: '李先生', tag: '待处理' },
  { id: 'w-3', name: '张女士', tag: '瑕疵咨询' },
  { id: 'w-4', name: '陈先生', tag: '退款跟进' },
];

export type MockWorkMessage = {
  id: string;
  from: 'user' | 'agent';
  content: string;
};

export const mockWorkMessages: MockWorkMessage[] = [
  { id: 'm-1', from: 'user', content: '这件衣服有轻微瑕疵，能处理吗？' },
  { id: 'm-2', from: 'agent', content: '已为您识别图片中的瑕疵位置，并同步售后策略。' },
];

export type MockVlmResult = {
  category: string;
  confidence: number; // 0-1，<0.6 转人工复核
  advice: string;
};

export const mockVlmResult: MockVlmResult = {
  category: '面料勾丝',
  confidence: 0.96,
  advice: '拍照留存后申请换货',
};

export type MockCitation = {
  source: string;
  title: string;
  score: number;
};

export const mockCitations: MockCitation[] = [
  { source: 'policy-3.2', title: '售后政策第3.2条', score: 0.92 },
  { source: 'flow-exchange', title: '换货处理流程', score: 0.87 },
];

export type MockCustomer = {
  level: string;
  order: string;
  traceId: string;
  status: string;
};

export const mockCustomer: MockCustomer = {
  level: 'VIP',
  order: '20260910',
  traceId: '8f3a91c2',
  status: '审批中',
};

// B端最小闭环演示数据（字段口径对齐 types/shop.ts，后端就绪后走真实接口）
export const mockGoods: GoodsItem[] = [
  {
    id: 'g-1',
    spu_no: 'HOODIE-25AW',
    name: '秋季连帽卫衣',
    category: '卫衣',
    status: 'on',
    status_label: '在售',
    images: [],
    attrs: {},
    created_at: '2026-09-01 10:00:00',
    skus: [
      {
        id: 's-1',
        sku_code: 'HOODIE-25AW-灰-M',
        color: '灰',
        size: 'M',
        barcode: '693001001',
        list_price: 25900,
        sale_price: 19900,
        status: 'on',
        status_label: '在售',
      },
      {
        id: 's-2',
        sku_code: 'HOODIE-25AW-黑-L',
        color: '黑',
        size: 'L',
        barcode: '693001002',
        list_price: 27900,
        sale_price: 21900,
        status: 'on',
        status_label: '在售',
      },
    ],
  },
  {
    id: 'g-2',
    spu_no: 'JEANS-042',
    name: '直筒牛仔裤',
    category: '裤装',
    status: 'on',
    status_label: '在售',
    images: [],
    attrs: {},
    created_at: '2026-09-02 10:00:00',
    skus: [
      {
        id: 's-3',
        sku_code: 'JEANS-042-蓝-30',
        color: '蓝',
        size: '30',
        barcode: '693002001',
        list_price: 32900,
        sale_price: 25900,
        status: 'on',
        status_label: '在售',
      },
    ],
  },
];

export const mockInventory: InventoryRow[] = [
  {
    id: 'i-1',
    warehouse_id: 'w-center',
    warehouse: '中心仓',
    sku_id: 's-1',
    spu_no: 'HOODIE-25AW',
    product_name: '秋季连帽卫衣',
    color: '灰',
    size: 'M',
    sku_code: 'HOODIE-25AW-灰-M',
    qty: 120,
    reserved: 20,
    locked: 5,
    available: 95,
    warn_line: 10,
    warning: false,
  },
  {
    id: 'i-2',
    warehouse_id: 'w-center',
    warehouse: '中心仓',
    sku_id: 's-3',
    spu_no: 'JEANS-042',
    product_name: '直筒牛仔裤',
    color: '蓝',
    size: '30',
    sku_code: 'JEANS-042-蓝-30',
    qty: 8,
    reserved: 2,
    locked: 0,
    available: 6,
    warn_line: 10,
    warning: true,
  },
  {
    id: 'i-3',
    warehouse_id: 'w-east',
    warehouse: '华东仓',
    sku_id: 's-2',
    spu_no: 'HOODIE-25AW',
    product_name: '秋季连帽卫衣',
    color: '黑',
    size: 'L',
    sku_code: 'HOODIE-25AW-黑-L',
    qty: 50,
    reserved: 0,
    locked: 0,
    available: 50,
    warn_line: 10,
    warning: false,
  },
];

export const mockOrders: OrderItem[] = [
  {
    id: 'o-1',
    platform: '淘宝',
    outer_id: 'TB-20260910001',
    status: 'paid',
    status_label: '待发货',
    total: 39800,
    item_count: 2,
    items: [],
    trace_id: '8f3a91c2',
    allowed_actions: ['ship'],
    company: '',
    tracking_no: '',
    created_at: '2026-09-10 09:12:00',
  },
  {
    id: 'o-2',
    platform: '抖店',
    outer_id: 'DD-884201',
    status: 'shipped',
    status_label: '已发货',
    total: 15900,
    item_count: 1,
    items: [],
    trace_id: '',
    allowed_actions: ['aftersale'],
    company: '中通',
    tracking_no: '7310123456',
    created_at: '2026-09-09 15:40:00',
  },
  {
    id: 'o-3',
    platform: '京东',
    outer_id: 'JD-552131',
    status: 'completed',
    status_label: '已完成',
    total: 29900,
    item_count: 1,
    items: [],
    trace_id: '',
    allowed_actions: ['aftersale'],
    company: '京东',
    tracking_no: 'JD00998877',
    created_at: '2026-09-08 11:20:00',
  },
];

// 审批演示数据（后端 /approvals 未就绪时占位，字段对齐 ApprovalItem）
export const mockApprovals: ApprovalItem[] = [
  {
    id: 'a-demo-1',
    action: 'price_change',
    action_label: '改价',
    target: 'HOODIE-25AW-灰-M',
    args: { old_price: 19900, new_price: 20900 },
    reason: '面料涨价',
    applicant: 'demo',
    approver: '',
    status: 'pending',
    status_label: '待审批',
    session_id: '',
    created_at: '2026-09-12 10:00:00',
    decided_at: '',
  },
  {
    id: 'a-demo-2',
    action: 'refund',
    action_label: '退款',
    target: 'TB-20260910001',
    args: { amount: 39800 },
    reason: '瑕疵退货',
    applicant: 'demo',
    approver: 'admin',
    status: 'approved',
    status_label: '已通过',
    session_id: '',
    created_at: '2026-09-11 09:00:00',
    decided_at: '2026-09-11 09:30:00',
  },
];

// 对话兜底回复（SSE 多次重连仍失败时本地回显，明确标注演示身份）
export const mockChatFallback =
  '网络开小差了，这是本地演示回复：退货政策是 7 天无理由、质量问题 15 天（演示数据，后端恢复后可重发）。';
