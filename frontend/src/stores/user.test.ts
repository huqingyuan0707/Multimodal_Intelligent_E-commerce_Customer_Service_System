// user store 单测（登录/登出/登录态恢复，对齐 AGENTS §4 验证要求）
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api';
import { useUserStore } from './user';

vi.mock('@/api', () => ({
  api: { me: vi.fn(), login: vi.fn(), logout: vi.fn() },
}));

const USER = { name: 'demo', tenant: 't1', roles: ['cs'], perms: ['cs'] };

// vitest 跑在 node 环境（vite.config.ts 未配 environment），用内存实现顶掉 sessionStorage
const createMemoryStorage = (): Storage => {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, String(value)),
    removeItem: (key: string) => void map.delete(key),
    clear: () => map.clear(),
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    get length() {
      return map.size;
    },
  } as Storage;
};

describe('useUserStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetAllMocks();
    vi.stubGlobal('sessionStorage', createMemoryStorage());
  });

  it('setUser/clearUser 切换登录态', () => {
    const store = useUserStore();
    expect(store.user).toBeNull();
    store.setUser(USER);
    expect(store.roles).toEqual(['cs']);
    expect(store.perms).toEqual(['cs']);
    store.clearUser();
    expect(store.user).toBeNull();
  });

  it('login 成功写入 token 并回填身份', async () => {
    vi.mocked(api.login).mockResolvedValue({ token: 'tk', user: USER });
    const store = useUserStore();
    const user = await store.login('demo', 'demo1234');
    expect(user.name).toBe('demo');
    expect(store.hasToken()).toBe(true);
    expect(store.user?.tenant).toBe('t1');
  });

  it('login 失败抛出中文提示且不落 token', async () => {
    vi.mocked(api.login).mockRejectedValue(new Error('用户名或密码错误'));
    const store = useUserStore();
    await expect(store.login('demo', 'bad')).rejects.toThrow('用户名或密码错误');
    expect(store.hasToken()).toBe(false);
    expect(store.user).toBeNull();
  });

  it('logout 清本地态（服务端确认失败也照常清）', async () => {
    vi.mocked(api.login).mockResolvedValue({ token: 'tk', user: USER });
    vi.mocked(api.logout).mockRejectedValue(new Error('net'));
    const store = useUserStore();
    await store.login('demo', 'demo1234');
    await store.logout();
    expect(store.hasToken()).toBe(false);
    expect(store.user).toBeNull();
  });

  it('loadMe 无 token 直接判失败且不打接口', async () => {
    const store = useUserStore();
    await expect(store.loadMe()).resolves.toBe(false);
    expect(api.me).not.toHaveBeenCalled();
  });

  it('loadMe 成功回填用户信息', async () => {
    vi.mocked(api.me).mockResolvedValue(USER);
    const store = useUserStore();
    sessionStorage.setItem('reai_token', 'tk');
    await expect(store.loadMe()).resolves.toBe(true);
    expect(store.user?.name).toBe('demo');
    expect(store.roles).toEqual(['cs']);
  });

  it('loadMe 失败（token 失效）判失败并清身份', async () => {
    vi.mocked(api.me).mockRejectedValue(new Error('401'));
    const store = useUserStore();
    sessionStorage.setItem('reai_token', 'tk');
    await expect(store.loadMe()).resolves.toBe(false);
    expect(store.user).toBeNull();
  });
});
