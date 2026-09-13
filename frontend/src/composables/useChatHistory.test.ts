// useChatHistory 单测（倒序页反转渲染 + has_more 加载更早前插 + 删除当前清空，对齐前端 Skill §8）
// getSessionApi 打桩，toAgentMessages 走真实映射（后端行形状），store 走真实 Pinia。
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { getSessionApi } from '@/api';
import type { AgentMessage } from '@/types/agent';
import { useChatHistory } from './useChatHistory';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, getSessionApi: vi.fn() };
});

const row = (content: string, role: string) => ({ content, role, modality: 'text' });

describe('useChatHistory', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetAllMocks();
  });

  it('restore 反转倒序页并记录 hasMore', async () => {
    vi.mocked(getSessionApi).mockResolvedValue({
      messages: [row('答', 'agent'), row('问', 'user')],
      has_more: true,
    });
    const messages = ref<AgentMessage[]>([]);
    const { hasMore, restore } = useChatHistory(messages);
    await restore('s-1');
    expect(messages.value.map(m => m.content)).toEqual(['问', '答']);
    expect(hasMore.value).toBe(true);
  });

  it('loadEarlier 前插更早页并翻页码', async () => {
    vi.mocked(getSessionApi)
      .mockResolvedValueOnce({ messages: [row('新', 'user')], has_more: true })
      .mockResolvedValueOnce({ messages: [row('旧', 'user')], has_more: false });
    const messages = ref<AgentMessage[]>([]);
    const { hasMore, restore, loadEarlier } = useChatHistory(messages);
    await restore('s-1');
    await loadEarlier();
    expect(messages.value.map(m => m.content)).toEqual(['旧', '新']);
    expect(hasMore.value).toBe(false);
  });

  it('forgetSession 只清空当前会话的消息区', async () => {
    vi.mocked(getSessionApi).mockResolvedValue({ messages: [row('问', 'user')], has_more: false });
    const messages = ref<AgentMessage[]>([]);
    const { restore, forgetSession } = useChatHistory(messages);
    await restore('s-1');
    forgetSession('other');
    expect(messages.value).toHaveLength(1);
    forgetSession('s-1');
    expect(messages.value).toEqual([]);
  });
});
