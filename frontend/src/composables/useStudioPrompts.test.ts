// useStudioPrompts 单测（版本列表映射/新建回填页/发布刷新线上，对齐 API 规范 §4.13）
// api 层打桩；失败向上传播由调用方 catch 提示（本层不断言兜底，只断言透出）
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createPromptApi,
  listPromptsApi,
  onlinePromptApi,
  publishPromptApi,
  rollbackPromptApi,
  setGrayPromptApi,
} from '@/api';
import type { PromptVersion } from '@/types/agent';
import { useStudioPrompts } from './useStudioPrompts';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return {
    ...mod,
    listPromptsApi: vi.fn(),
    createPromptApi: vi.fn(),
    publishPromptApi: vi.fn(),
    setGrayPromptApi: vi.fn(),
    rollbackPromptApi: vi.fn(),
    onlinePromptApi: vi.fn(),
  };
});

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

describe('useStudioPrompts', () => {
  beforeEach(() => vi.resetAllMocks());

  it('refresh 映射版本列表与分页总数', async () => {
    vi.mocked(listPromptsApi).mockResolvedValue({
      items: [row('v13', 'gray'), row('v12', 'online')],
      total: 2,
      page: 1,
      size: 20,
    });
    const { versions, total, refresh } = useStudioPrompts();
    await refresh();
    expect(total.value).toBe(2);
    expect(versions.value.map(v => v.version)).toEqual(['v13', 'v12']);
  });

  it('create 后回填第一页并返回新行', async () => {
    vi.mocked(createPromptApi).mockResolvedValue(row('v14', 'draft'));
    vi.mocked(listPromptsApi).mockResolvedValue({
      items: [row('v14', 'draft')],
      total: 3,
      page: 1,
      size: 20,
    });
    const { page, versions, create } = useStudioPrompts();
    const created = await create('新话术', '你是客服。');
    expect(created.version).toBe('v14');
    expect(page.value).toBe(1);
    expect(versions.value.length).toBe(1);
  });

  it('publish 后刷新列表与线上版本', async () => {
    vi.mocked(publishPromptApi).mockResolvedValue(row('v13', 'online'));
    vi.mocked(listPromptsApi).mockResolvedValue({
      items: [row('v13', 'online')],
      total: 1,
      page: 1,
      size: 20,
    });
    vi.mocked(onlinePromptApi).mockResolvedValue(row('v13', 'online'));
    const { online, hasOnline, publish } = useStudioPrompts();
    await publish('v13', 100);
    expect(online.value?.version).toBe('v13');
    expect(hasOnline.value).toBe(true);
  });

  it('setGray/rollback 走对应接口并刷新', async () => {
    vi.mocked(setGrayPromptApi).mockResolvedValue({ ...row('v13', 'gray'), gray: 80 });
    vi.mocked(rollbackPromptApi).mockResolvedValue(row('v12', 'online'));
    vi.mocked(listPromptsApi).mockResolvedValue({ items: [], total: 0, page: 1, size: 20 });
    vi.mocked(onlinePromptApi).mockResolvedValue(row('v12', 'online'));
    const { setGray, rollback, online } = useStudioPrompts();
    expect((await setGray('v13', 80)).gray).toBe(80);
    expect((await rollback('v12')).status).toBe('online');
    expect(online.value?.version).toBe('v12');
  });

  it('接口失败向上传播（页面置空并中文提示，本层不吞错）', async () => {
    vi.mocked(listPromptsApi).mockRejectedValue(new Error('网络错误'));
    const { versions, refresh } = useStudioPrompts();
    await expect(refresh()).rejects.toThrow('网络错误');
    expect(versions.value).toEqual([]);
  });
});
