// B端商家后台类型先行（商品/库存/订单；字段口径对齐后端 service_to_dict，金额一律分；对齐页面设计 §3.10/3.11/3.13）
export type PageResult<T> = {
  total: number;
  page: number;
  size: number;
  items: T[];
};

export type GoodsStatus = 'draft' | 'on' | 'off' | 'archived';

export type SkuItem = {
  id: string;
  sku_code: string;
  color: string;
  size: string;
  barcode: string;
  list_price: number;
  sale_price: number;
  available: number;
  status: string;
  status_label: string;
};

// 商品变更同步客服知识结果（FR-10.1，对齐 PUT /goods/skus/{sku_id} 与 PUT /goods/{product_id}/status 响应的 kb_doc 字段）
export type KbDocInfo = {
  doc_id: string;
  title: string;
  version: number;
};

export type GoodsItem = {
  id: string;
  spu_no: string;
  name: string;
  category: string;
  status: GoodsStatus;
  status_label: string;
  images: string[];
  attrs: object;
  sales: number;
  created_at: string;
  skus: SkuItem[];
  kb_doc?: KbDocInfo | null;
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

// 出入库流水（倒序；kind 中文走 kind_label，对齐 GET /inventory/moves）
// kind 口径：in 入库 / out 出库 / move 调拨（用户可提交）；adjust 调整仅系统内部（盘点审批生效）
export type StockMoveItem = {
  id: string;
  warehouse_id: string;
  sku_id: string;
  kind: string;
  kind_label: string;
  delta: number;
  reason: string;
  order_ref: string;
  actor: string;
  created_at: string;
};

export type OrderStatus = 'pending_pay' | 'paid' | 'shipped' | 'completed' | 'aftersale' | 'closed';

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
  logistics_id: string;
  logistics_status: string;
  created_at: string;
};

// 金额分转元展示（后端金额字段一律分，页面禁止裸展示分）
export const formatCents = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

// 状态中文走后端 status_label；此处只定胶囊颜色（枚举中文化映射表，对齐 Skill §5）
// el-table 行类型为 DefaultRow，模板内经 tagOf* 收口，避免模板里写 as 断言
export const GOODS_TAG = {
  on: 'success',
  off: 'info',
  draft: 'warning',
  archived: 'info',
} as const;

export const ORDER_TAG = {
  pending_pay: 'warning',
  paid: 'primary',
  shipped: 'info',
  completed: 'success',
  aftersale: 'danger',
  closed: 'info',
} as const;

export type TagColor = 'success' | 'info' | 'warning' | 'primary' | 'danger';

// 售后单（关联客服会话 trace_id，可跳回原会话，对齐 FRD 附录 D/页面设计 §3.13）
// evidence 为证据图 URL 列表（建单时逗号分隔提交，列表/详情原样返回）
// disposition 为质检处置位（pending/restocked/scrapped/returned，后端中文走 disposition_label）
export type AftersaleItem = {
  id: string;
  order_id: string;
  reason: string;
  amount: number;
  evidence: string[];
  trace_id: string;
  status: string;
  status_label: string;
  disposition: string;
  disposition_label: string;
  created_at: string;
};

// 模板内 el-table 行是 DefaultRow：收口为 string 入参，未知状态兜底 info（后端加状态不断前端）
export const goodsTagOf = (status: string) => GOODS_TAG[status as keyof typeof GOODS_TAG] ?? 'info';

export const orderTagOf = (status: string) => ORDER_TAG[status as keyof typeof ORDER_TAG] ?? 'info';

export const AFTERSALE_TAG = {
  pending: 'warning',
  approving: 'primary',
  done: 'success',
} as const;

export const aftersaleTagOf = (status: string) =>
  AFTERSALE_TAG[status as keyof typeof AFTERSALE_TAG] ?? 'info';

// 质检处置位胶囊（restocked 二次入库 / scrapped 报损 / returned 退供；未处置默认 info）
export const DISPOSITION_TAG = {
  restocked: 'success',
  scrapped: 'danger',
  returned: 'info',
} as const;

export const dispositionTagOf = (disposition: string) =>
  DISPOSITION_TAG[disposition as keyof typeof DISPOSITION_TAG] ?? 'info';

// 营销与会员（预算/积分口径对齐后端 promo_service；对齐页面设计 §3.16）
// budget/granted/remaining 单位：张（计数，非金额）；valid_from/valid_to 空串=不限
export type PromoItem = {
  id: string;
  name: string;
  budget: number;
  granted: number;
  total: number;
  per_user: number;
  status: string;
  remaining: number;
  valid_from: string;
  valid_to: string;
  created_at: string;
};

// 发券记录（幂等键回放对账用，对齐 POST /promos/{id}/grant）
export type CouponGrantItem = {
  id: string;
  promo_id: string;
  user_ref: string;
  order_ref: string;
  status: string;
  idem_key: string;
  created_at: string;
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

export const REVIEW_TAG = {
  good: 'success',
  mid: 'warning',
  bad: 'danger',
} as const;

export const TICKET_TAG = {
  open: 'warning',
  doing: 'primary',
  closed: 'success',
} as const;

// 物流运单（状态中文走后端 status_label；对齐 GET /logistics/track）
export type LogisticsItem = {
  id: string;
  sales_order_id: string;
  company: string;
  tracking_no: string;
  status: string;
  status_label: string;
  created_at: string;
};

export const LOGISTICS_TAG = {
  created: 'info',
  picked: 'primary',
  in_transit: 'warning',
  exception: 'danger',
} as const;

export const logisticsTagOf = (status: string) =>
  LOGISTICS_TAG[status as keyof typeof LOGISTICS_TAG] ?? 'info';
export const reviewTagOf = (status: string) =>
  REVIEW_TAG[status as keyof typeof REVIEW_TAG] ?? 'info';

export const ticketTagOf = (status: string) =>
  TICKET_TAG[status as keyof typeof TICKET_TAG] ?? 'info';
