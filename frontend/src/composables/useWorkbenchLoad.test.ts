// useWorkbenchLoad 单测（负载面板数据 + 失败静默降级：技能组筛选隐藏/分配禁用，对齐 FR-7）
// loadWorkbenchApi 打桩；node 环境无 DOM 依赖（纯数据 composable）
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadWorkbenchApi, type WorkbenchLoad } from '@/api';
import { useWorkbenchLoad } from './useWorkbenchLoad';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, loadWorkbenchApi: vi.fn() };
});

const payload: WorkbenchLoad = {
  limit: 5,
  enabled: true,
  agents: [
    {
      username: 'cs_refund',
      handling: 2,
      limit: 5,
      at_capacity: false,
      skills: ['general', 'refund'],
    },
    { username: 'cs_general', handling: 0, limit: 5, at_capacity: false, skills: ['general'] },
  ],
  pending_by_skill: { refund: 1, general: 3 },
  skill_groups: [
    { key: 'general', label: '通用' },
    { key: 'refund', label: '退款售后' },
  ],
};

describe('useWorkbenchLoad', () => {
  beforeEach(() => vi.resetAllMocks());

  it('refresh 成功映射面板：组清单/分配开关/坐席负载/各组待接数', async () => {
    vi.mocked(loadWorkbenchApi).mockResolvedValue(payload);
    const { skillGroups, assignEnabled, loadLimit, agents, pendingBySkill, refresh } =
      useWorkbenchLoad();
    await refresh();
    expect(skillGroups.value.map(g => g.key)).toEqual(['general', 'refund']);
    expect(assignEnabled.value).toBe(true);
    expect(loadLimit.value).toBe(5);
    expect(agents.value.find(a => a.username === 'cs_refund')?.handling).toBe(2);
    expect(pendingBySkill.value.refund).toBe(1);
  });

  it('接口失败静默降级：组清单空（筛选行隐藏）+ 分配禁用，不抛错', async () => {
    vi.mocked(loadWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { skillGroups, assignEnabled, panel, refresh } = useWorkbenchLoad();
    await expect(refresh()).resolves.toBeNull();
    expect(panel.value).toBeNull();
    expect(skillGroups.value).toEqual([]);
    expect(assignEnabled.value).toBe(false);
  });

  it('上限 0（关闭分配）时 enabled=false 但组清单仍可用', async () => {
    vi.mocked(loadWorkbenchApi).mockResolvedValue({ ...payload, limit: 0, enabled: false });
    const { skillGroups, assignEnabled, refresh } = useWorkbenchLoad();
    await refresh();
    expect(assignEnabled.value).toBe(false);
    expect(skillGroups.value.length).toBe(2);
  });
});
