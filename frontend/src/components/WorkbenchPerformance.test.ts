// WorkbenchPerformance 组件测试：坐席绩效弹窗（C 步收官，对齐页面设计 §3.2）
// 覆盖：打开拉数据渲染行/口径说明/失败置空表+中文提示；teleport 就地渲染便于断言
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WorkbenchPerformance from './WorkbenchPerformance.vue';
import {
  performanceWorkbenchApi,
  type WorkbenchPerformance as WorkbenchPerformanceData,
} from '@/api';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, performanceWorkbenchApi: vi.fn() };
});

// jsdom 无 ResizeObserver（el-table 内部依赖），桩掉
class ROStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver =
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ?? ROStub;

const perfRow = (overrides: object = {}) => ({
  assignee: 'admin',
  resolved: 3,
  scored: 2,
  avg_score: 3.5,
  pass_rate: 0.5,
  manual_reviews: 1,
  unscored: 1,
  ...overrides,
});

const perfData = (overrides: object = {}): WorkbenchPerformanceData => ({
  pass_score: 4,
  auto_enabled: true,
  agents: [perfRow()],
  ...overrides,
});

const mountPerf = (modelValue = true) =>
  mount(WorkbenchPerformance, {
    props: { modelValue },
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  });

describe('workbenchPerformance', () => {
  beforeEach(() => vi.resetAllMocks());

  it('打开拉取绩效并渲染坐席行与口径说明', async () => {
    vi.mocked(performanceWorkbenchApi).mockResolvedValue(perfData());
    const wrapper = mountPerf();
    await vi.dynamicImportSettled();
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('坐席绩效');
    expect(wrapper.text()).toContain('质检通过线 4 分');
    expect(wrapper.text()).toContain('自动评分已开启');
    expect(wrapper.text()).toContain('admin');
    expect(wrapper.text()).toContain('50%');
    expect(wrapper.text()).toContain('3.5');
  });

  it('接口失败置空表 + 中文提示（不编造绩效）', async () => {
    vi.mocked(performanceWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const wrapper = mountPerf();
    await vi.dynamicImportSettled();
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('暂无已解决会话');
  });

  it('modelValue=false 不渲染弹窗内容也不打接口', () => {
    mountPerf(false);
    expect(performanceWorkbenchApi).not.toHaveBeenCalled();
  });
});
