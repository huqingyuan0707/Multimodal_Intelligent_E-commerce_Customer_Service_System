// StudioEvalPane 组件测试（一键跑上抛/红条/历史查看，对齐页面设计 §3.6）
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it } from 'vitest';
import { nextTick } from 'vue';

import StudioEvalPane from './StudioEvalPane.vue';
import type { EvalRun } from '@/types/agent';

const donePass: EvalRun = {
  id: 'e-1',
  name: 'default-200',
  limit: 3,
  status: 'done',
  score: {
    total: 3,
    answerable: 2,
    refuse: 1,
    grounded: 1,
    hallucination: 0,
    per_scene: {},
    guard_dist: {},
    misses: [],
    ratchet_ok: true,
    accept_ok: true,
  },
  pass: true,
  accept: true,
  elapsed_ms: 100,
  error: '',
  created_by: 'admin',
  created_at: '2026-09-17 10:00:00',
};

const doneFail: EvalRun = { ...donePass, id: 'e-2', pass: false, accept: false };

const mountPane = (props: object = {}) =>
  mount(StudioEvalPane, {
    props: {
      runs: [donePass],
      total: 1,
      page: 1,
      size: 20,
      current: donePass,
      loading: false,
      running: false,
      ...props,
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  });

afterEach(() => {
  document.body.innerHTML = '';
});

// el-table 行渲染走 rAF/布局节流，jsdom 下需放行几帧才可见
const settled = async () => {
  await nextTick();
  await new Promise(resolve => {
    setTimeout(resolve, 150);
  });
  await nextTick();
};

describe('StudioEvalPane', () => {
  it('达标显示验收结论，不挂红条', async () => {
    const wrapper = mountPane();
    await settled();
    expect(wrapper.text()).toContain('达验收线可发布');
    expect(wrapper.text()).not.toContain('不达标禁发布');
    wrapper.unmount();
  });

  it('未达标挂红条禁发布', async () => {
    const wrapper = mountPane({ current: doneFail, runs: [doneFail] });
    await settled();
    expect(wrapper.text()).toContain('不达标禁发布');
    wrapper.unmount();
  });

  it('一键跑上抛 run（name+limit）', async () => {
    const wrapper = mountPane({ current: null, runs: [] });
    await settled();
    const run = wrapper.findAll('button').find(b => b.text().includes('一键跑'));
    expect(run).toBeTruthy();
    await run!.trigger('click');
    expect(wrapper.emitted('run')).toEqual([[{ name: 'default-200', limit: 50 }]]);
    wrapper.unmount();
  });

  it('历史查看上抛 run id', async () => {
    const wrapper = mountPane();
    await settled();
    const view = wrapper.findAll('button').find(b => b.text().includes('查看'));
    expect(view).toBeTruthy();
    await view!.trigger('click');
    expect(wrapper.emitted('view')).toEqual([['e-1']]);
    wrapper.unmount();
  });
});
