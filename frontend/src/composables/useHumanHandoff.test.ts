// useHumanHandoff 单测（t- 占位先落库认领 + 后端会话直接挂起 + 失败不追加提示行，对齐前端 Skill §8）
// api 打桩；session store 走真实 Pinia（内存态）。
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createSessionApi, handoffWorkbenchApi } from '@/api';
import { useSessionStore } from '@/stores/session';
import { useHumanHandoff } from './useHumanHandoff';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, createSessionApi: vi.fn(), handoffWorkbenchApi: vi.fn() };
});

// ElMessage 弹 DOM，node 测试环境桩掉
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn() },
}));

// 收集系统提示行的探针（模拟视图 appendSystem）
const appended: string[] = [];

describe('useHumanHandoff', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetAllMocks();
    appended.length = 0;
  });

  it('t- 占位会话先落库建会话再挂起', async () => {
    vi.mocked(createSessionApi).mockResolvedValue({ id: 's-real', title: '转人工会话' });
    vi.mocked(handoffWorkbenchApi).mockResolvedValue({ handoff_status: 'pending' });
    const store = useSessionStore();
    store.$patch({
      sessions: [{ id: 't-1', title: '占位会话' }] as never,
      currentId: 't-1',
    });
    const { transfer } = useHumanHandoff();
    await transfer(c => appended.push(c));
    expect(createSessionApi).toHaveBeenCalledOnce();
    expect(handoffWorkbenchApi).toHaveBeenCalledWith({ id: 's-real', reason: '买家主动请求人工' });
    // 占位认领为后端会话
    expect(store.currentId).toBe('s-real');
    expect(appended).toEqual(['已为你转人工，坐席将在 30 秒内接管，请留意回复。']);
  });

  it('已有后端会话直接挂起不重复建', async () => {
    vi.mocked(handoffWorkbenchApi).mockResolvedValue({ handoff_status: 'pending' });
    const store = useSessionStore();
    store.$patch({ sessions: [{ id: 's-1', title: '会话' }] as never, currentId: 's-1' });
    const { transfer } = useHumanHandoff();
    await transfer(c => appended.push(c));
    expect(createSessionApi).not.toHaveBeenCalled();
    expect(handoffWorkbenchApi).toHaveBeenCalledWith({ id: 's-1', reason: '买家主动请求人工' });
    expect(store.currentId).toBe('s-1');
  });

  it('handoff 失败不追加系统提示行', async () => {
    vi.mocked(handoffWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const store = useSessionStore();
    store.$patch({ sessions: [{ id: 's-1', title: '会话' }] as never, currentId: 's-1' });
    const { transferring, transfer } = useHumanHandoff();
    await transfer(c => appended.push(c));
    expect(appended).toEqual([]);
    expect(transferring.value).toBe(false);
  });
});
