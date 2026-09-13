// session store 单测（t- 占位认领 + 列表降级，对齐前端 Skill §8 改 store 必补用例）
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listSessionsApi } from '@/api';
import { mockSessions } from '@/mock';
import { useSessionStore } from './session';

vi.mock('@/api', () => ({
  listSessionsApi: vi.fn(),
}));

vi.mock('@/mock', () => ({
  mockSessions: [{ id: 'm-1', title: '演示会话' }],
}));

describe('useSessionStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetAllMocks();
  });

  it('createLocalSession 建 t- 占位并置为当前', () => {
    const store = useSessionStore();
    const id = store.createLocalSession();
    expect(id.startsWith('t-')).toBe(true);
    expect(store.currentId).toBe(id);
    expect(store.sessions[0]?.id).toBe(id);
  });

  it('adoptSession 用后端 id 替换占位并回填标题', () => {
    const store = useSessionStore();
    const local = store.createLocalSession();
    store.adoptSession(local, 'backend-1', '退货政策');
    expect(store.sessions[0]).toEqual({ id: 'backend-1', title: '退货政策' });
    expect(store.currentId).toBe('backend-1');
  });

  it('adoptSession 不动非当前会话的 currentId', () => {
    const store = useSessionStore();
    const local = store.createLocalSession();
    store.currentId = 'other';
    store.adoptSession(local, 'backend-1', '退货政策');
    expect(store.currentId).toBe('other');
    expect(store.sessions[0]?.id).toBe('backend-1');
  });

  it('loadSessions 失败回退 mock 演示数据', async () => {
    vi.mocked(listSessionsApi).mockRejectedValue(new Error('net'));
    const store = useSessionStore();
    await store.loadSessions();
    expect(store.sessions).toEqual(mockSessions);
  });

  it('loadSessions 成功采用后端列表', async () => {
    const rows = [{ id: 's-1', title: ' histories ' }];
    vi.mocked(listSessionsApi).mockResolvedValue(rows);
    const store = useSessionStore();
    await store.loadSessions();
    expect(store.sessions).toEqual(rows);
  });
});
