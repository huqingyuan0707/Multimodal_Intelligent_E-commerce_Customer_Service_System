// B端商家后台类型先行（商品/库存/订单；字段口径对齐后端 service_to_dict，金额一律分；对齐页面设计 §3.10/3.11/3.13）
export type PageResult<T> = {
  total: number;
  page: number;
  size: number;
  items: T[];
};

export type GoodsStatus = 'draft' | 'on' | 'off';

export type SkuItem = {
  id: string;
  sku_code: string;
  color: string;
  size: string;
  barcode: string;
  list_price: number;
  sale_price: number;
  status: string;
  status_label: string;
};

export type GoodsItem = {
  id: string;
  spu_no: string;
  name: string;
  category: string;
  status: GoodsStatus;
  status_label: string;
  images: string[];
  attrs: Record<string, unknown>;
  created_at: string;
  skus: SkuItem[];
};

export type InventoryRow = {
  id: string;
  warehouse_id: string;
  warehouse: string;
  sku_id: string;
  spu_no: string;
  product_name: string;
  color: string;
  size: string;
  sku_code: string;
  qty: number;
  reserved: number;
  locked: number;
  available: number;
  warn_line: number;
  warning: boolean;
};

export type OrderStatus =
  | 'pending_pay'
  | 'paid'
  | 'shipped'
  | 'completed'
  | 'aftersale'
  | 'closed';

export type OrderItem = {
  id: string;
  platform: string;
  outer_id: string;
  status: OrderStatus;
  status_label: string;
  total: number;
  item_count: number;
  items: unknown[];
  trace_id: string;
  allowed_actions: string[];
  company: string;
  tracking_no: string;
  created_at: string;
};

// 金额分转元展示（后端金额字段一律分，页面禁止裸展示分）
export const formatCents = (cents: number): string => `¥${(cents / 100).toFixed(2)}`;

// 状态中文走后端 status_label；此处只定胶囊颜色（枚举中文化映射表，对齐 Skill §5）
// el-table 行类型为 DefaultRow，模板内经 tagOf* 收口，避免模板里写 as 断言
export const GOODS_TAG: Record<GoodsStatus, 'success' | 'info' | 'warning'> = {
  on: 'success',
  off: 'info',
  draft: 'warning',
};

export const ORDER_TAG: Record<
  OrderStatus,
  'success' | 'info' | 'warning' | 'primary' | 'danger'
> = {
  pending_pay: 'warning',
  paid: 'primary',
  shipped: 'info',
  completed: 'success',
  aftersale: 'danger',
  closed: 'info',
};

export type TagColor = 'success' | 'info' | 'warning' | 'primary' | 'danger';

// 售后单（关联客服会话 trace_id，可跳回原会话，对齐 FRD 附录 D/页面设计 §3.13）
export type AftersaleItem = {
  id: string;
  order_id: string;
  reason: string;
  amount: number;
  trace_id: string;
  status: string;
  status_label: string;
  created_at: string;
};

// 模板内 el-table 行是 DefaultRow：收口为 string 入参，未知状态兜底 info（后端加状态不断前端）
export const goodsTagOf = (status: string): TagColor =>
  (GOODS_TAG as Record<string, TagColor>)[status] ?? 'info';

export const orderTagOf = (status: string): TagColor =>
  (ORDER_TAG as Record<string, TagColor>)[status] ?? 'info';

// 营销与会员（预算/积分口径对齐后端 promo_service；对齐页面设计 §3.16）
export type PromoItem = {
  id: string;
  name: string;
  budget: number;
  granted: number;
  total: number;
  per_user: number;
  status: string;
  remaining: number;
};

export type MemberItem = {
  user_ref: string;
  level: string;
  points: number;
};

// 评价与工单（差评 ticket 双向可跳；对齐页面设计 §3.17/§3.18）
export type ReviewItem = {
  id: string;
  platform: string;
  outer_id: string;
  level: string;
  content: string;
  tags: string[];
  replied: boolean;
  reply: string;
  ticket_id: string;
  created_at: string;
};

export type TicketItem = {
  id: string;
  kind: string;
  source_ref: string;
  assignee: string;
  sla_due: string;
  status: string;
  conclusion: string;
  created_at: string;
};

export const REVIEW_TAG: Record<string, TagColor> = {
  good: 'success',
  mid: 'warning',
  bad: 'danger',
};

export const TICKET_TAG: Record<string, TagColor> = {
  open: 'warning',
  doing: 'primary',
  closed: 'success',
};

export const reviewTagOf = (status: string): TagColor =>
  (REVIEW_TAG as Record<string, TagColor>)[status] ?? 'info';

export const ticketTagOf = (status: string): TagColor =>
  (TICKET_TAG as Record<string, TagColor>)[status] ?? 'info';
