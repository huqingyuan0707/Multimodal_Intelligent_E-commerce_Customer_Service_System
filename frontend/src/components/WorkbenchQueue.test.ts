// WorkbenchQueue 组件测试：左栏队列（服务端分页版，对齐页面设计 §3.2 + 前端 Skill §7）
// 覆盖：行渲染/选中态/页签上抛 filter/搜索防抖 300ms/空态/分页事件
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { describe, expect, it, vi } from 'vitest';

import WorkbenchQueue from './WorkbenchQueue.vue';
import type { QueueRow } from '@/composables/useWorkbenchQueue';

const rows: QueueRow[] = [
  {
    id: 'h1',
    name: '王小明',
    title: '退货咨询',
    statusKey: 'pending',
    statusLabel: '待接',
    assignee: '',
    reason: '情绪激动',
    skill: 'refund',
    skillLabel: '退款售后',
    queuePosition: 1,
    lastMessage: '我要退那个充电宝',
    updatedAt: '2026-09-16T00:12:31',
    vip: true,
  },
  {
    id: 'h2',
    name: '李雷',
    title: '物流查询',
    statusKey: 'handling',
    statusLabel: '处理中',
    assignee: 'admin',
    reason: '',
    skill: 'general',
    skillLabel: '通用',
    queuePosition: 0,
    lastMessage: '',
    updatedAt: '2026-09-16T00:05:00',
    vip: false,
  },
];

const baseProps = {
  rows,
  currentId: 'h1',
  total: 57,
  page: 1,
  size: 20,
  status: 'open',
  skill: '',
  skillGroups: [],
  loading: false,
};

const mountQueue = (props: object = {}) =>
  mount(WorkbenchQueue, {
    props: { ...baseProps, ...props },
    global: { plugins: [ElementPlus] },
  });

describe('workbenchQueue', () => {
  it('渲染队列行：姓名/预览/坐席/状态标签/VIP，空预览回落 reason→占位', () => {
    const wrapper = mountQueue();
    const items = wrapper.findAll('.item');
    expect(items).toHaveLength(2);
    expect(items[0].find('.name').text()).toBe('王小明');
    expect(items[0].find('.row2').text()).toBe('我要退那个充电宝');
    expect(items[0].text()).toContain('VIP');
    expect(items[0].text()).toContain('退款售后');
    expect(items[0].text()).toContain('排队第 1 位');
    expect(items[1].text()).not.toContain('排队第');
    expect(items[1].find('.row2').text()).toBe('暂无消息');
    expect(items[1].text()).toContain('坐席 admin');
    expect(items[0].text()).toContain('未分配');
  });

  it('仅 currentId 行选中，点击上抛 select', async () => {
    const wrapper = mountQueue();
    const items = wrapper.findAll('.item');
    expect(items[0].classes()).toContain('item-on');
    expect(items[1].classes()).not.toContain('item-on');
    await items[1].trigger('click');
    expect(wrapper.emitted('select')?.[0]).toEqual(['h2']);
  });

  it('页签：当前 status 高亮，点击上抛 filter(key)', async () => {
    const wrapper = mountQueue();
    const chips = wrapper.findAll('.chip');
    expect(chips[0].classes()).toContain('chip-on'); // status=open
    await chips[3].trigger('click');
    expect(wrapper.emitted('filter')?.[0]).toEqual(['resolved']);
  });

  it('搜索 300ms 防抖：连续输入只上抛一次最终词', async () => {
    vi.useFakeTimers();
    try {
      const wrapper = mountQueue();
      await wrapper.find('input').setValue('退');
      await wrapper.find('input').setValue('退款');
      expect(wrapper.emitted('search')).toBeUndefined();
      vi.advanceTimersByTime(301);
      const events = wrapper.emitted('search');
      expect(events).toHaveLength(1);
      expect(events?.[0]).toEqual(['退款']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('rows 空且非 loading 才出空态', () => {
    const empty = mountQueue({ rows: [] });
    expect(empty.findAll('.item')).toHaveLength(0);
    expect(empty.find('.el-empty').exists()).toBe(true);
    const loading = mountQueue({ rows: [], loading: true });
    expect(loading.find('.el-empty').exists()).toBe(false);
  });

  it('头部计数：loading 显文案，否则显 total', () => {
    expect(mountQueue().find('.count').text()).toBe('57 条');
    expect(mountQueue({ loading: true }).find('.count').text()).toBe('加载中…');
  });
});
