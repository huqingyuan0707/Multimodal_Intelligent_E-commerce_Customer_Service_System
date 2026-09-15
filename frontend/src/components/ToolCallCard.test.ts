// ToolCallCard 组件测试：透明展示 done.tool_calls（对齐 API 规范 §4.12 / 画板 wtk00 族）
// 覆盖：空不渲染 / 状态 pill（成功·待审批·被拒）/ meta 口径 / 默认展开可折叠 / 结果摘要 / notes
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import ToolCallCard from './ToolCallCard.vue';
import type { ToolCall } from '@/types/agent';

const okCall: ToolCall = {
  tool: 'order.query',
  status: 'ok',
  scope: 'demo-tenant',
  args: { outer_id: 'SO-1' },
  result: { outer_id: 'SO-1', status_label: '已发货' },
  attempts: 1,
  latency_ms: 42,
  trace_id: 'tr-1',
};

const approvalCall: ToolCall = {
  tool: 'refund.apply',
  status: 'ok',
  approval_required: true,
  approval_id: 'ap-1234567890',
  result: {},
  latency_ms: 10,
};

const rejectedCall: ToolCall = {
  tool: 'stock.update',
  status: 'rejected',
  code: 3001,
  message: '无权操作该仓库库存',
  args: { sku: 'A1' },
  trace_id: 'tr-2',
};

describe('toolCallCard', () => {
  it('无调用且无说明时不渲染任何节点', () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [], notes: [] } });
    expect(wrapper.find('.tools').exists()).toBe(false);
    expect(wrapper.text()).toBe('');
  });

  it('ok 调用：标题/成功 pill/meta 口径（scope·耗时·次数·trace）', () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [okCall], notes: [] } });
    expect(wrapper.find('.title').text()).toBe('工具调用 · order.query');
    expect(wrapper.find('.pill').classes()).toContain('ok');
    expect(wrapper.find('.pill').text()).toBe('成功');
    expect(wrapper.find('.meta').text()).toBe(
      'scope demo-tenant · 耗时 0.04s · 1 次 · trace_id tr-1',
    );
  });

  it('approval_required：pill 待审批 + 结果句明示账目未变动', () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [approvalCall], notes: [] } });
    expect(wrapper.find('.pill').text()).toBe('待审批');
    expect(wrapper.find('.res').text()).toContain('已提交审批（账目未变动）');
    expect(wrapper.find('.res').text()).toContain('ap-1234567890');
  });

  it('默认展开参果，点折叠按钮收起再点恢复', async () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [okCall], notes: [] } });
    expect(wrapper.find('.arg').text()).toContain('"outer_id":"SO-1"');
    const fold = wrapper.find('.fold');
    expect(fold.attributes('aria-expanded')).toBe('true');
    await fold.trigger('click');
    expect(wrapper.find('.arg').exists()).toBe(false);
    expect(wrapper.find('.res').exists()).toBe(false);
    expect(fold.attributes('aria-expanded')).toBe('false');
    await fold.trigger('click');
    expect(wrapper.find('.arg').exists()).toBe(true);
  });

  it('rejected：被拒 pill + 如实透出原因句', () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [rejectedCall], notes: [] } });
    expect(wrapper.find('.pill').text()).toBe('被拒');
    expect(wrapper.find('.res').text()).toContain('无权操作该仓库库存');
  });

  it('已知工具走专属摘要句', () => {
    const wrapper = mount(ToolCallCard, { props: { calls: [okCall], notes: [] } });
    expect(wrapper.find('.res').text()).toBe('结果 订单 SO-1 当前为「已发货」');
  });

  it('notes 合并为一条编排说明（分号连接，不编造）', () => {
    const wrapper = mount(ToolCallCard, {
      props: { calls: [], notes: ['缺少收件地址，未调用改址工具', '库存工具无权调用'] },
    });
    const notes = wrapper.findAll('.note');
    expect(notes).toHaveLength(1);
    expect(notes[0].text()).toBe('编排说明 · 缺少收件地址，未调用改址工具；库存工具无权调用');
  });
});
