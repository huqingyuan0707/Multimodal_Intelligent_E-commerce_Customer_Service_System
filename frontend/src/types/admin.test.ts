// 管理后台展示口径测试（FR-8）：缺数据必须显示「—」，绝不拿 0 冒充 ——
// 后端用 no_data/no_score 标了「没测过」，前端如果渲染成 0 就把这个区分抹掉了。
import { describe, expect, it } from 'vitest';
import {
  apiKeyStatusTagOf,
  formatRate,
  formatSloValue,
  sloOperatorLabelOf,
  sloUnitLabelOf,
  templateStatusTagOf,
  tenantPlanTagOf,
  userStatusTagOf,
} from './admin';

describe('admin 数值展示口径', () => {
  it('SLO 缺数据回「—」，比率标 %、秒与次数带单位', () => {
    expect(formatSloValue(null, 'ratio')).toBe('—');
    expect(formatSloValue(0.9521, 'ratio')).toBe('95.21%');
    expect(formatSloValue(12, 'seconds')).toBe('12 秒');
    expect(formatSloValue(3, 'count')).toBe('3 次');
  });

  it('到达率/解决率：缺数据「—」，真实的 0 照实显示 0.0%', () => {
    expect(formatRate(null)).toBe('—');
    expect(formatRate(0)).toBe('0.0%');
    expect(formatRate(0.875)).toBe('87.5%');
  });

  it('未知枚举回退为 info 标签，不抛错（后端加枚举时前端不白屏）', () => {
    expect(apiKeyStatusTagOf('active')).toBe('success');
    expect(apiKeyStatusTagOf('unknown-status')).toBe('info');
    expect(userStatusTagOf('frozen')).toBe('danger');
    expect(templateStatusTagOf('draft')).toBe('info');
    expect(tenantPlanTagOf('pro')).toBe('success');
  });

  it('SLO 方向与单位中文化来自映射表，模板不再散落字面量', () => {
    expect(sloOperatorLabelOf('gte')).toBe('不低于');
    expect(sloOperatorLabelOf('lte')).toBe('不高于');
    expect(sloUnitLabelOf('ratio')).toBe('比例');
    expect(sloUnitLabelOf('weird')).toBe('weird');
  });
});
