// Shop 域纯函数单测（金额格式化 + 胶囊颜色收口，未知状态不断言崩）
import { describe, expect, it } from 'vitest';
import { approvalTagOf } from '@/types/approval';
import { formatCents, goodsTagOf, orderTagOf } from '@/types/shop';
import { hasPerm } from '@/shared/directives/permission';

describe('formatCents', () => {
  it('分转元保留两位', () => {
    expect(formatCents(19900)).toBe('¥199.00');
    expect(formatCents(0)).toBe('¥0.00');
  });
});

describe('tagOf 收口', () => {
  it('已知状态映射正确', () => {
    expect(goodsTagOf('on')).toBe('success');
    expect(orderTagOf('paid')).toBe('primary');
    expect(approvalTagOf('pending')).toBe('warning');
  });

  it('未知状态兜底 info', () => {
    expect(goodsTagOf('whatever')).toBe('info');
    expect(orderTagOf('whatever')).toBe('info');
    expect(approvalTagOf('whatever')).toBe('info');
  });
});

describe('hasPerm', () => {
  it('无要求直接放行', () => {
    expect(hasPerm(undefined)).toBe(true);
    expect(hasPerm([])).toBe(true);
  });
});
