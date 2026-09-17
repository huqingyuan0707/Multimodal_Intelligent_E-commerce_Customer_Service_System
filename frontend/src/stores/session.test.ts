// session store 单测（t- 占位认领 + 列表失败置空，对齐前端 Skill §8 改 store 必补用例）
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listSessionsApi } from '@/api';
import { useSessionStore } from './session';

vi.mock('@/api', () => ({
  listSessionsApi: vi.fn(),
}));

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }));

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

  it('loadSessions 失败置空不编造数据', async () => {
    vi.mocked(listSessionsApi).mockRejectedValue(new Error('net'));
    const store = useSessionStore();
    await store.loadSessions();
    expect(store.sessions).toEqual([]);
    expect(store.total).toBe(0);
  });

  it('loadSessions 成功采用后端分页对象', async () => {
    const rows = [{ id: 's-1', title: ' histories ' }];
    vi.mocked(listSessionsApi).mockResolvedValue({ items: rows, total: 3, page: 1, size: 20 });
    const store = useSessionStore();
    await store.loadSessions();
    expect(store.sessions).toEqual(rows);
    expect(store.total).toBe(3);
  });

  it('loadSessions 兼容旧数组信封', async () => {
    const rows = [{ id: 's-1', title: 'old' }];
    vi.mocked(listSessionsApi).mockResolvedValue(rows);
    const store = useSessionStore();
    await store.loadSessions();
    expect(store.sessions).toEqual(rows);
    expect(store.total).toBe(1);
  });

  it('loadSessions 切页大小后透传 size 并回第 1 页语义', async () => {
    vi.mocked(listSessionsApi).mockResolvedValue({ items: [], total: 0, page: 1, size: 10 });
    const store = useSessionStore();
    await store.loadSessions(1, 10);
    expect(store.size).toBe(10);
    expect(vi.mocked(listSessionsApi)).toHaveBeenCalledWith({ page: 1, size: 10 });
  });

  it('renameLocal 改标题不动其他行', async () => {
    const store = useSessionStore();
    store.sessions = [
      { id: 's-1', title: 'a' },
      { id: 's-2', title: 'b' },
    ];
    store.renameLocal('s-1', '改名');
    expect(store.sessions[0]?.title).toBe('改名');
    expect(store.sessions[1]?.title).toBe('b');
  });

  it('removeLocal 删行并清理 currentId', async () => {
    const store = useSessionStore();
    store.sessions = [{ id: 's-1', title: 'a' }];
    store.total = 1;
    store.currentId = 's-1';
    store.removeLocal('s-1');
    expect(store.sessions).toEqual([]);
    expect(store.total).toBe(0);
    expect(store.currentId).toBeNull();
  });
});
