// VersionDrawer 组件测试：版本抽屉（对齐页面设计 §3.5 + FR-13.2）
// 覆盖：打开拉版本列表/当前版按钮禁用/空态
// 注意：el-drawer teleport 到 body，挂载用 attachTo + 查 document.body
// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it, vi } from 'vitest';

import VersionDrawer from './VersionDrawer.vue';

const { versionsMock } = vi.hoisted(() => ({ versionsMock: vi.fn() }));

vi.mock('@/api', () => ({
  docVersionsApi: versionsMock,
  rollbackDocApi: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = '';
});

const mountDrawer = (props: object = {}) =>
  mount(VersionDrawer, {
    props: { visible: false, docId: 'd1', title: '退货政策', currentVersion: 2, ...props },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  });

describe('versionDrawer', () => {
  it('打开时拉版本列表并渲染动作列', async () => {
    versionsMock.mockReset();
    versionsMock.mockResolvedValue({
      items: [
        {
          version: 2,
          title: '退货政策',
          content: 'v2',
          sha256: 'b',
          actor: 'bob',
          action: 'update',
          created_at: '2026-09-17 10:00:00',
        },
        {
          version: 1,
          title: '退货政策',
          content: 'v1',
          sha256: 'a',
          actor: 'alice',
          action: 'create',
          created_at: '2026-09-16 10:00:00',
        },
      ],
    });
    const wrapper = mountDrawer();
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(versionsMock).toHaveBeenCalledWith({ id: 'd1' });
    const text = document.body.textContent ?? '';
    expect(text).toContain('当前版');
    expect(text).toContain('回滚到此版');
  });

  it('版本为空出空态', async () => {
    versionsMock.mockReset();
    versionsMock.mockResolvedValue({ items: [] });
    const wrapper = mountDrawer();
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(document.body.textContent ?? '').toContain('暂无版本记录');
  });
});
