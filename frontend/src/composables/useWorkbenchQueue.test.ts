// useWorkbenchQueue 单测（真实队列映射 + 服务端筛选/分页透传 + 失败回退演示挂标 + 认领后重拉保当前）
// queueWorkbenchApi/claimWorkbenchApi 打桩；ElMessage/ElMessageBox 弹 DOM，node 环境桩掉（对齐前端 Skill §8）
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { claimWorkbenchApi, queueWorkbenchApi, type WorkbenchRow } from '@/api';
import { useWorkbenchQueue } from './useWorkbenchQueue';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, queueWorkbenchApi: vi.fn(), claimWorkbenchApi: vi.fn() };
});

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn() },
  ElMessageBox: { prompt: vi.fn() },
}));

const row = (id: string, status: string, assignee = ''): WorkbenchRow => ({
  id,
  title: `会话 ${id}`,
  username: '买家小张',
  created_at: '2026-09-14T10:00:00',
  updated_at: '2026-09-14T10:30:00',
  message_count: 6,
  handoff_status: status,
  handoff_label: '待接',
  assignee,
  handoff_reason: '买家主动请求人工',
  resolution: '',
  last_message: '袖口脱线约2cm可换货处理',
});

const paged = (items: WorkbenchRow[]) => ({ items, total: items.length, page: 1, size: 20 });

describe('useWorkbenchQueue', () => {
  beforeEach(() => vi.resetAllMocks());

  it('load 映射真实队列为页面行形状并自动选中首行', async () => {
    vi.mocked(queueWorkbenchApi).mockResolvedValue(
      paged([row('s-1', 'pending'), row('s-2', 'handling', 'cs01')]),
    );
    const { rows, total, demo, currentId, currentRow, load } = useWorkbenchQueue();
    await load();
    expect(demo.value).toBe(false);
    expect(total.value).toBe(2);
    expect(rows.value[0]).toEqual({
      id: 's-1',
      name: '买家小张',
      title: '会话 s-1',
      statusKey: 'pending',
      statusLabel: '待接',
      assignee: '',
      reason: '买家主动请求人工',
      lastMessage: '袖口脱线约2cm可换货处理',
      updatedAt: '2026-09-14T10:30:00',
      vip: false,
    });
    expect(rows.value[1]?.assignee).toBe('cs01');
    expect(currentId.value).toBe('s-1');
    expect(currentRow.value?.id).toBe('s-1');
  });

  it('筛选/分页参数透传后端，默认页大小 20', async () => {
    vi.mocked(queueWorkbenchApi).mockResolvedValue(paged([]));
    const { load, setStatus, setSize } = useWorkbenchQueue();
    await load();
    expect(queueWorkbenchApi).toHaveBeenLastCalledWith({
      status: 'open',
      q: '',
      page: 1,
      size: 20,
    });
    await setSize(50);
    expect(queueWorkbenchApi).toHaveBeenLastCalledWith({
      status: 'open',
      q: '',
      page: 1,
      size: 50,
    });
    await setStatus('pending');
    expect(queueWorkbenchApi).toHaveBeenLastCalledWith({
      status: 'pending',
      q: '',
      page: 1,
      size: 50,
    });
  });

  it('后端不可用回退演示种子并挂 demo 标', async () => {
    vi.mocked(queueWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { rows, demo, currentId, load } = useWorkbenchQueue();
    await load();
    expect(demo.value).toBe(true);
    expect(rows.value.length).toBeGreaterThan(0);
    expect(rows.value[0]).toMatchObject({ statusKey: 'pending', vip: true });
    expect(currentId.value).toBe(rows.value[0]?.id);
  });

  it('认领成功调后端并重拉；当前会话不在新集合也不切走（keep）', async () => {
    vi.mocked(queueWorkbenchApi)
      .mockResolvedValueOnce(paged([row('s-1', 'pending')]))
      .mockResolvedValueOnce(paged([row('s-9', 'pending')]));
    vi.mocked(claimWorkbenchApi).mockResolvedValue({ handoff_status: 'handling' });
    const { load, claim, currentId } = useWorkbenchQueue();
    await load();
    expect(currentId.value).toBe('s-1');
    expect(await claim()).toBe(true);
    expect(claimWorkbenchApi).toHaveBeenCalledWith({ id: 's-1' });
    expect(queueWorkbenchApi).toHaveBeenCalledTimes(2);
    expect(currentId.value).toBe('s-1');
  });

  it('未选中会话时不发动作请求', async () => {
    const { claim, transfer, resolve, handoff } = useWorkbenchQueue();
    expect(await claim()).toBe(false);
    expect(await transfer()).toBe(false);
    expect(await resolve()).toBe(false);
    expect(await handoff()).toBe(false);
    expect(claimWorkbenchApi).not.toHaveBeenCalled();
  });

  it('认领失败不静默：返回 false 且提示', async () => {
    vi.mocked(queueWorkbenchApi).mockResolvedValue(paged([row('s-1', 'pending')]));
    vi.mocked(claimWorkbenchApi).mockRejectedValue(new Error('已被他人认领'));
    const { load, claim } = useWorkbenchQueue();
    await load();
    expect(await claim()).toBe(false);
    expect(queueWorkbenchApi).toHaveBeenCalledTimes(1);
  });
});
