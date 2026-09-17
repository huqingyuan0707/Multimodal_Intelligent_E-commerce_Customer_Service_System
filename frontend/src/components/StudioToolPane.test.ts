// StudioToolPane 组件测试（工具清单渲染/试调上抛/审批提示回显，对齐 API 规范 §4.12）
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it } from 'vitest';
import { nextTick } from 'vue';

import StudioToolPane from './StudioToolPane.vue';
import type { StudioTool } from '@/types/agent';

const tools: StudioTool[] = [
  {
    name: 'order.query',
    scope: 'cs',
    description: '查单',
    params: { order_id: 'string' },
    idempotent: true,
    requires_approval: false,
    approval_action: '',
    timeout_seconds: 30,
    max_retries: 3,
    breaker: { failures: 0, open: false },
  },
];

const mountPane = (props: object = {}) =>
  mount(StudioToolPane, {
    props: { tools, loading: false, trialing: false, trialResult: null, ...props },
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

describe('StudioToolPane', () => {
  it('渲染工具名/Scope/超时/幂等', async () => {
    const wrapper = mountPane();
    await settled();
    expect(wrapper.text()).toContain('order.query');
    expect(wrapper.text()).toContain('30s');
    expect(wrapper.text()).toContain('是');
    wrapper.unmount();
  });

  it('试调对话框确认后上抛 trial（name+argsText）', async () => {
    const wrapper = mountPane();
    await settled();
    const trial = wrapper.findAll('button').find(b => b.text() === '试调');
    expect(trial).toBeTruthy();
    await trial!.trigger('click');
    await nextTick();
    await nextTick();
    const area = document.body.querySelector('.el-dialog textarea') as HTMLTextAreaElement;
    expect(area).toBeTruthy();
    area.value = '{"order_id":"1"}';
    area.dispatchEvent(new Event('input'));
    await nextTick();
    const els = [...document.body.querySelectorAll('.el-dialog button')];
    const confirm = els.find(el => el.textContent === '试调') as HTMLElement;
    expect(confirm).toBeTruthy();
    confirm.click();
    await nextTick();
    expect(wrapper.emitted('trial')).toEqual([
      [{ name: 'order.query', argsText: '{"order_id":"1"}' }],
    ]);
    wrapper.unmount();
  });

  it('审批试调结果回显审批单号（账不动提示）', async () => {
    const wrapper = mountPane({
      trialResult: {
        tool: 'refund.create',
        status: 'ok',
        approval_required: true,
        approval_id: 'a-1',
      },
    });
    await settled();
    const trial = wrapper.findAll('button').find(b => b.text() === '试调');
    await trial!.trigger('click');
    await nextTick();
    await nextTick();
    expect(document.body.textContent).toContain('a-1');
    wrapper.unmount();
  });
});
