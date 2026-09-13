// 数据看板演示兜底（后端 /observability/summary 未就绪时回退，保证页面可用，对齐前端 Skill §6）
// 口径对齐页面设计 §3.7：指标卡 6 项 + 按租户/渠道归因表
import type { AttributionRow, DashboardMetric } from '@/types/dashboard';

export const mockMetrics: DashboardMetric[] = [
  { key: 'qps', label: '问答 QPS', value: '12.4', desc: '每秒问答请求数（网关统计）', overBudget: false },
  { key: 'p95', label: '首字 P95', value: '1.62s', desc: '流式首字延迟 P95（目标 <2s）', overBudget: false },
  { key: 'resolve', label: '自动解决率', value: '81.3%', desc: '一次解决无需转人工占比', overBudget: false },
  { key: 'hallucination', label: '幻觉率', value: '1.8%', desc: '无引用/引用越界回答占比（目标 ≤2%）', overBudget: false },
  { key: 'tool', label: '工具成功率', value: '97.6%', desc: '业务连接器调用成功占比', overBudget: false },
  { key: 'cost', label: 'Token 成本', value: '¥128.40', desc: '本期累计模型费用，超预算标红', overBudget: true },
];

export const mockAttributions: AttributionRow[] = [
  {
    id: 'a-1',
    tenant: 'demo-tenant',
    channel: 'taobao',
    sessions: 420,
    resolveRate: '82.1%',
    costCents: 4520,
    overBudget: false,
    slowTraceId: '8f3a91c2',
  },
  {
    id: 'a-2',
    tenant: 'demo-tenant',
    channel: 'doudian',
    sessions: 310,
    resolveRate: '79.4%',
    costCents: 3980,
    overBudget: false,
    slowTraceId: 'b71c04de',
  },
  {
    id: 'a-3',
    tenant: 'demo-tenant',
    channel: 'pdd',
    sessions: 188,
    resolveRate: '84.0%',
    costCents: 2140,
    overBudget: false,
    slowTraceId: 'c9d2f177',
  },
  {
    id: 'a-4',
    tenant: 'demo-tenant',
    channel: 'jd',
    sessions: 142,
    resolveRate: '77.8%',
    costCents: 5210,
    overBudget: true,
    slowTraceId: 'e410aa93',
  },
  {
    id: 'a-5',
    tenant: 'demo-tenant',
    channel: 'widget',
    sessions: 96,
    resolveRate: '88.5%',
    costCents: 1180,
    overBudget: false,
    slowTraceId: 'f2c88b10',
  },
];
