// 经营大屏演示兜底（后端 /screen/summary 未就绪回退；金额已脱敏展示，对齐页面设计 §3.15）
export type ScreenMetric = {
  key: string;
  label: string;
  value: string;
  tone: 'up' | 'good' | 'bad' | 'warn';
};

export const mockScreenMetrics: ScreenMetric[] = [
  { key: 'gmv', label: 'GMV（今日/昨日）', value: '￥86,400 ↑12%', tone: 'up' },
  { key: 'solve', label: '自动解决率 / 幻觉率', value: '83% / 1.4%', tone: 'good' },
  { key: 'return', label: '退货率 · Top原因脱线', value: '6.2% · 预警1款', tone: 'bad' },
  { key: 'stock', label: '缺货SKU / 安全预警', value: '3 / 5', tone: 'warn' },
];

export type ScreenTrendPoint = {
  label: string;
  value: number;
};

export const mockScreenTrend: ScreenTrendPoint[] = [
  { label: '周一', value: 60 },
  { label: '周二', value: 90 },
  { label: '周三', value: 70 },
  { label: '周四', value: 120 },
  { label: '周五', value: 100 },
  { label: '周六', value: 140 },
  { label: '今日', value: 170 },
];

export type ScreenWarning = {
  id: string;
  content: string;
  level: 'bad' | 'info';
};

export const mockScreenWarnings: ScreenWarning[] = [
  { id: 'w-1', content: '卫衣退货率突增 → 会话/质检下钻 → 已补知识待回归', level: 'bad' },
  { id: 'w-2', content: '白/M 库存低于安全线 → 话术已切“补货中”', level: 'info' },
];
