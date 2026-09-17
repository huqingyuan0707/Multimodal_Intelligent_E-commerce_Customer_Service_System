// WorkbenchQc 组件测试：质检评分卡（C 步收官，对齐页面设计 §3.2 + 前端 Skill §7）
// 覆盖：空态/评分展示（来源标签+通过 tag+依据）/改评表单校验与上抛
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { describe, expect, it } from 'vitest';

import WorkbenchQc from './WorkbenchQc.vue';
import type { WorkbenchScore } from '@/api';

const scoreRow = (overrides: object = {}): WorkbenchScore => ({
  id: 'sc-1',
  session_id: 's-1',
  assignee: 'admin',
  score: 4,
  resolution_ok: true,
  source: 'judge',
  reviewer: '',
  detail: { reason: '回复准确，问题已解决', messages: 6 },
  pass: true,
  updated_at: '2026-09-16 10:00:00',
  ...overrides,
});

const baseProps = {
  score: null as WorkbenchScore | null,
  loading: false,
  saving: false,
};

const mountQc = (props: object = {}) =>
  mount(WorkbenchQc, {
    props: { ...baseProps, ...props },
    global: { plugins: [ElementPlus] },
  });

describe('workbenchQc', () => {
  it('未评会话出空态引导文案，不渲染改评表单', () => {
    const wrapper = mountQc();
    expect(wrapper.text()).toContain('会话解决后自动评分');
    expect(wrapper.find('.form').exists()).toBe(false);
  });

  it('loading 中显加载态', () => {
    expect(mountQc({ loading: true }).text()).toContain('评分加载中');
  });

  it('有评分：综合分/通过 tag/AI 评审标签/依据/复核人齐全', () => {
    const wrapper = mountQc({ score: scoreRow() });
    expect(wrapper.find('.big').text()).toBe('4');
    expect(wrapper.text()).toContain('质检通过');
    expect(wrapper.text()).toContain('AI 评审');
    expect(wrapper.find('.reason').text()).toBe('回复准确，问题已解决');
  });

  it('人工复核来源显示 reviewer，未达标显红色 tag', () => {
    const wrapper = mountQc({
      score: scoreRow({ score: 2, pass: false, source: 'manual', reviewer: 'admin' }),
    });
    expect(wrapper.text()).toContain('人工复核');
    expect(wrapper.text()).toContain('复核人 admin');
    expect(wrapper.text()).toContain('未达标');
  });

  it('改评：表单回填当前评分，直接提交上抛；点星改分后上抛新值', async () => {
    const wrapper = mountQc({ score: scoreRow() });
    // watch immediate 回填 score=4 → 直接提交即上抛当前值
    await wrapper.find('.form button').trigger('click');
    let events = wrapper.emitted('save');
    expect(events).toHaveLength(1);
    expect(events?.[0][0]).toMatchObject({ score: 4, resolution_ok: true, comment: '' });
    // 点第 5 颗星改分后再次提交 → 上抛新值
    await wrapper.findAll('.el-rate__item')[4].trigger('click');
    await wrapper.find('.form button').trigger('click');
    events = wrapper.emitted('save');
    expect(events).toHaveLength(2);
    expect(events?.[1][0]).toMatchObject({ score: 5 });
  });

  it('切换 score 回填表单（清空改评草稿防串场）', async () => {
    const wrapper = mountQc({ score: scoreRow() });
    await wrapper.setProps({ score: scoreRow({ score: 2, resolution_ok: false }) });
    await wrapper.findAll('.el-rate__item')[1].trigger('click');
    await wrapper.find('.form button').trigger('click');
    expect(wrapper.emitted('save')?.[0][0]).toMatchObject({ score: 2, resolution_ok: false });
  });
});
