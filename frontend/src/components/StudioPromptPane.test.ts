// StudioPromptPane 组件测试（版本列表渲染/新建发布回滚上抛/分页事件，对齐页面设计 §3.6）
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it } from 'vitest';
import { nextTick } from 'vue';

import StudioPromptPane from './StudioPromptPane.vue';
import type { PromptVersion } from '@/types/agent';

const row = (version: string, status: PromptVersion['status']): PromptVersion => ({
  id: `p-${version}`,
  version,
  desc: `${version}说明`,
  content: '你是客服。',
  variables: [],
  gray: status === 'online' ? 100 : 0,
  status,
  status_label: status,
  created_by: 'admin',
  created_at: '2026-09-17 10:00:00',
  updated_at: '2026-09-17 10:00:00',
});

const baseProps = {
  versions: [row('v13', 'gray'), row('v12', 'online')],
  total: 2,
  page: 1,
  size: 20,
  loading: false,
};

const mountPane = (props: object = {}) =>
  mount(StudioPromptPane, {
    props: { ...baseProps, ...props },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  });

afterEach(() => {
  document.body.innerHTML = '';
});

// el-table 行渲染走 rAF/布局节流，jsdom 下需放行几帧才可见（WorkbenchQueue 系手写 div，无此问题）
const settled = async () => {
  await nextTick();
  await new Promise(resolve => {
    setTimeout(resolve, 150);
  });
  await nextTick();
};

// 行内按钮（teleport 外，直查本组件树即可）
const rowButton = (wrapper: ReturnType<typeof mountPane>, text: string) => {
  const hit = wrapper.findAll('button').find(b => b.text() === text);
  expect(hit, `找不到行按钮：${text}`).toBeTruthy();
  return hit!;
};

// 对话框经 teleport 挂 body，直查 document（组件树内查不到）
const dlgButton = async (text: string) => {
  await nextTick();
  await nextTick();
  const els = [...document.body.querySelectorAll('.el-dialog button')];
  const hit = els.find(el => el.textContent?.includes(text));
  expect(hit, `找不到对话框按钮：${text}`).toBeTruthy();
  return hit as HTMLElement;
};

const dlgInput = async (index: number, value: string) => {
  await nextTick();
  const areas = document.body.querySelectorAll('.el-dialog textarea, .el-dialog input');
  const el = areas[index] as HTMLInputElement | undefined;
  expect(el, '对话框输入框缺失').toBeTruthy();
  el!.value = value;
  el!.dispatchEvent(new Event('input'));
  await nextTick();
};

describe('StudioPromptPane', () => {
  it('渲染版本号/灰度/状态签', async () => {
    const wrapper = mountPane();
    await settled();
    expect(wrapper.text()).toContain('v13');
    expect(wrapper.text()).toContain('灰度中');
    expect(wrapper.text()).toContain('线上');
    wrapper.unmount();
  });

  it('新建对话框确认后上抛 create（desc+content）', async () => {
    const wrapper = mountPane();
    await settled();
    await rowButton(wrapper, '新建版本').trigger('click');
    await dlgInput(0, '新话术');
    await dlgInput(1, '你是客服。{{city}}');
    (await dlgButton('创建草稿')).click();
    await nextTick();
    expect(wrapper.emitted('create')).toEqual([
      [{ desc: '新话术', content: '你是客服。{{city}}' }],
    ]);
    wrapper.unmount();
  });

  it('发布对话框确认后上抛 publish（version+gray）', async () => {
    const grayRow = { ...row('v13', 'gray'), gray: 50 };
    const wrapper = mountPane({ versions: [grayRow, row('v12', 'online')] });
    await settled();
    await rowButton(wrapper, '发布').trigger('click');
    (await dlgButton('确认发布')).click();
    await nextTick();
    const emitted = wrapper.emitted('publish') as { version: string; gray: number }[][];
    expect(emitted[0][0].version).toBe('v13');
    expect(emitted[0][0].gray).toBe(50);
    wrapper.unmount();
  });

  it('回滚按钮直接上抛版本号（二次确认由页面承担）', async () => {
    const wrapper = mountPane();
    await settled();
    await rowButton(wrapper, '回滚').trigger('click');
    expect(wrapper.emitted('rollback')).toEqual([['v13']]);
    wrapper.unmount();
  });

  it('分页切换上抛 page-change/size-change', async () => {
    const wrapper = mountPane();
    await settled();
    const pager = wrapper.findComponent({ name: 'ElPagination' });
    pager.vm.$emit('current-change', 2);
    pager.vm.$emit('size-change', 50);
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted('page-change')).toEqual([[2]]);
    expect(wrapper.emitted('size-change')).toEqual([[50]]);
    wrapper.unmount();
  });
});
