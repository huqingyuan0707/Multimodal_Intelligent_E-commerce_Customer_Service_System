// useWorkbenchTrace 单测（真实 Trace 映射历史/引用/上下文 + 失败回退演示种子 + append 本地追加）
// traceWorkbenchApi 打桩，toAgentMessages 走真实实现（页面消费形状由 API 层收口，对齐前端 Skill §8）
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { traceWorkbenchApi } from '@/api';
import { useWorkbenchTrace } from './useWorkbenchTrace';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, traceWorkbenchApi: vi.fn() };
});

const trace = {
  session: { handoff_reason: '买家投诉瑕疵', resolution: '已按 15 天质量问题换货' },
  messages: [
    { role: 'user', content: '这件衣服有瑕疵' },
    {
      role: 'agent',
      content: '已识别瑕疵位置',
      trace_id: 'tr-1',
      citations: [{ source: 'policy-3.2', title: '售后政策第3.2条', score: 0.9 }],
    },
  ],
  context: {
    summary: '已摘要',
    rounds: 3,
    tokens: 900,
    dropped: 1,
    budget: 3000,
    window_rounds: 6,
  },
};

describe('useWorkbenchTrace', () => {
  beforeEach(() => vi.resetAllMocks());

  it('load 映射真实 Trace：消息/引用/上下文/流转字段', async () => {
    vi.mocked(traceWorkbenchApi).mockResolvedValue(trace);
    const { messages, context, summary, reasoning, demo, load } = useWorkbenchTrace();
    await load('s-1');
    expect(traceWorkbenchApi).toHaveBeenCalledWith({ id: 's-1' });
    expect(messages.value).toHaveLength(2);
    expect(messages.value[0]).toMatchObject({ id: 'h-0', role: 'user', content: '这件衣服有瑕疵' });
    expect(messages.value[1]?.references?.[0]?.title).toBe('售后政策第3.2条');
    expect(messages.value[1]?.trace_id).toBe('tr-1');
    expect(context.value?.tokens).toBe(900);
    expect(reasoning.value).toBe('买家投诉瑕疵');
    expect(summary.value).toBe('已按 15 天质量问题换货');
    expect(demo.value).toBe(false);
  });

  it('空会话 id 直接清空不打接口', async () => {
    const { messages, context, load } = useWorkbenchTrace();
    await load('');
    expect(traceWorkbenchApi).not.toHaveBeenCalled();
    expect(messages.value).toEqual([]);
    expect(context.value).toBeNull();
  });

  it('后端不可用回退演示种子并挂 demo 标（不阻塞工作台）', async () => {
    vi.mocked(traceWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { messages, context, demo, load, loading } = useWorkbenchTrace();
    await load('s-1');
    expect(demo.value).toBe(true);
    expect(messages.value.length).toBeGreaterThan(0);
    expect(context.value).toBeNull();
    expect(loading.value).toBe(false);
  });

  it('append 本地追加代回消息，不重拉全量', async () => {
    vi.mocked(traceWorkbenchApi).mockResolvedValue(trace);
    const { messages, append, load } = useWorkbenchTrace();
    await load('s-1');
    append({ id: 'cs-1', role: 'agent', modality: 'text', content: '已为您申请换货' });
    expect(messages.value).toHaveLength(3);
    expect(messages.value[2]?.content).toBe('已为您申请换货');
    expect(traceWorkbenchApi).toHaveBeenCalledTimes(1);
  });
});
