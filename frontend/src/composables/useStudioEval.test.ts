// useStudioEval 单测（一键跑建 run 即返/轮询到 done/历史映射，对齐 API 规范 §4.13）
// api 层打桩；轮询定时器用假时钟推进，不真实等待
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createEvalRunApi, getEvalRunApi, listEvalRunsApi } from '@/api';
import type { EvalRun } from '@/types/agent';
import { useStudioEval } from './useStudioEval';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, createEvalRunApi: vi.fn(), getEvalRunApi: vi.fn(), listEvalRunsApi: vi.fn() };
});

const run = (status: EvalRun['status']): EvalRun => ({
  id: 'e-1',
  name: 'default-200',
  limit: 3,
  status,
  score: {
    total: 3,
    answerable: 2,
    refuse: 1,
    grounded: 1,
    hallucination: 0,
    per_scene: {},
    guard_dist: {},
    misses: [],
    ratchet_ok: true,
    accept_ok: true,
  },
  pass: status === 'done',
  accept: status === 'done',
  elapsed_ms: 100,
  error: '',
  created_by: 'admin',
  created_at: '2026-09-17 10:00:00',
});

describe('useStudioEval', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
  });

  it('startRun 建 run 即返并轮询到 done', async () => {
    vi.mocked(createEvalRunApi).mockResolvedValue(run('pending'));
    vi.mocked(getEvalRunApi).mockResolvedValueOnce(run('running')).mockResolvedValue(run('done'));
    const { current, running, startRun } = useStudioEval();
    const promise = startRun('default-200', 3);
    await vi.advanceTimersByTimeAsync(5000);
    const final = await promise;
    expect(final.status).toBe('done');
    expect(current.value?.status).toBe('done');
    expect(running.value).toBe(false);
  });

  it('refreshRuns 映射历史与总数', async () => {
    vi.mocked(listEvalRunsApi).mockResolvedValue({
      items: [run('done')],
      total: 1,
      page: 1,
      size: 20,
    });
    const { runs, total, refreshRuns } = useStudioEval();
    await refreshRuns();
    expect(total.value).toBe(1);
    expect(runs.value[0].pass).toBe(true);
  });

  it('接口失败向上传播（页面置空并中文提示）', async () => {
    vi.mocked(listEvalRunsApi).mockRejectedValue(new Error('网络错误'));
    const { refreshRuns } = useStudioEval();
    await expect(refreshRuns()).rejects.toThrow('网络错误');
  });
});
