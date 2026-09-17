// 经营大屏类型先行（4 指标 + 近 7 日趋势 + 预警下钻；口径对齐页面设计 §3.15 + FRD FR-9）
// 链路：BizScreenView → api/screen → 后端 /screen/summary（screen_service 聚合，无回退数据）
export type ScreenMetric = {
  key: string;
  label: string;
  value: string;
  tone: 'up' | 'good' | 'bad' | 'warn';
};

export type ScreenTrendPoint = {
  label: string;
  value: number;
};

export type ScreenWarning = {
  id: string;
  content: string;
  level: 'bad' | 'info';
};
