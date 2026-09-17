// useWorkbenchQc 单测（质检评分读取 + 人工改评覆盖 + 失败置空不打断主链路，对齐前端 Skill §8）
// getScoreWorkbenchApi/saveScoreWorkbenchApi 打桩；ElMessage 弹 DOM，node 环境桩掉
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getScoreWorkbenchApi, saveScoreWorkbenchApi, type WorkbenchScore } from '@/api';
import { useWorkbenchQc } from './useWorkbenchQc';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, getScoreWorkbenchApi: vi.fn(), saveScoreWorkbenchApi: vi.fn() };
});

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

const scoreRow = (overrides: object = {}): WorkbenchScore => ({
  id: 'sc-1',
  session_id: 's-1',
  assignee: 'admin',
  score: 4,
  resolution_ok: true,
  source: 'judge',
  reviewer: '',
  detail: { reason: '基本解决', messages: 6 },
  pass: true,
  updated_at: '2026-09-16 10:00:00',
  ...overrides,
});

describe('useWorkbenchQc', () => {
  beforeEach(() => vi.resetAllMocks());

  it('load 拉取评分', async () => {
    vi.mocked(getScoreWorkbenchApi).mockResolvedValue(scoreRow());
    const { score, loading, load } = useWorkbenchQc();
    await load('s-1');
    expect(loading.value).toBe(false);
    expect(score.value?.score).toBe(4);
    expect(score.value?.source).toBe('judge');
  });

  it('未选中会话清空不打接口', async () => {
    const { score, load } = useWorkbenchQc();
    await load('');
    expect(getScoreWorkbenchApi).not.toHaveBeenCalled();
    expect(score.value).toBeNull();
  });

  it('load 失败置空并提示（不打断主链路）', async () => {
    vi.mocked(getScoreWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { score, load } = useWorkbenchQc();
    await load('s-1');
    expect(score.value).toBeNull();
  });

  it('save 成功用返回值刷新卡片并提示', async () => {
    vi.mocked(saveScoreWorkbenchApi).mockResolvedValue(
      scoreRow({ score: 2, source: 'manual', reviewer: 'admin', pass: false }),
    );
    const { score, saving, save } = useWorkbenchQc();
    const okFlag = await save('s-1', { score: 2, resolution_ok: false, comment: '未确认运单' });
    expect(okFlag).toBe(true);
    expect(saveScoreWorkbenchApi).toHaveBeenCalledWith({
      id: 's-1',
      score: 2,
      resolution_ok: false,
      comment: '未确认运单',
    });
    expect(score.value?.source).toBe('manual');
    expect(score.value?.reviewer).toBe('admin');
    expect(saving.value).toBe(false);
  });

  it('save 失败提示且不覆盖当前评分', async () => {
    vi.mocked(saveScoreWorkbenchApi).mockRejectedValue(new Error('评分保存失败'));
    const { score, save } = useWorkbenchQc();
    expect(await save('s-1', { score: 5, resolution_ok: true, comment: '' })).toBe(false);
    expect(score.value).toBeNull();
  });

  it('reset 清空评分', async () => {
    vi.mocked(getScoreWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { load, reset } = useWorkbenchQc();
    await load('s-1');
    reset();
  });
});
