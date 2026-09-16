// useChatFeedback 单测（赞踩提交/置灰、埋点静默失败、限流与网络错误两种收尾，对齐前端 Skill §8）
// submitFeedbackApi/trackEventApi 打桩；messages 用 ref 注入，不依赖页面。
// @vitest-environment jsdom（ElMessage 弹 DOM，node 环境无 document）
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { submitFeedbackApi, trackEventApi } from '@/api';
import type { AgentMessage } from '@/types/agent';
import { useChatFeedback } from './useChatFeedback';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return {
    ...mod,
    submitFeedbackApi: vi.fn(),
    trackEventApi: vi.fn(),
  };
});

const agentMsg = (patch: Partial<AgentMessage> = {}): AgentMessage => ({
  id: 'a-1',
  role: 'agent',
  modality: 'text',
  content: '支持 7 天无理由退货 [1]。',
  message_id: 'm-1',
  ...patch,
});

describe('useChatFeedback', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetAllMocks();
    vi.mocked(trackEventApi).mockResolvedValue(undefined);
  });

  it('vote 提交成功写 message.feedback 并埋点', async () => {
    vi.mocked(submitFeedbackApi).mockResolvedValue({ id: 'f-1' });
    const messages = ref<AgentMessage[]>([agentMsg()]);
    const { vote } = useChatFeedback(messages);
    await vote(messages.value[0], 'down');
    expect(submitFeedbackApi).toHaveBeenCalledWith({ message_id: 'm-1', vote: 'down' });
    expect(messages.value[0].feedback).toBe('down');
    expect(trackEventApi).toHaveBeenCalledWith('chat.feedback', { vote: 'down' });
  });

  it('vote 已有反馈或无 message_id 不重复提交', async () => {
    const messages = ref<AgentMessage[]>([
      agentMsg({ feedback: 'up' }),
      agentMsg({ id: 'a-2', message_id: '' }),
    ]);
    const { vote } = useChatFeedback(messages);
    await vote(messages.value[0], 'down');
    await vote(messages.value[1], 'down');
    expect(submitFeedbackApi).not.toHaveBeenCalled();
  });

  it('vote 失败提示且不置灰', async () => {
    vi.mocked(submitFeedbackApi).mockRejectedValue(new Error('消息不存在'));
    const messages = ref<AgentMessage[]>([agentMsg()]);
    const { vote } = useChatFeedback(messages);
    await vote(messages.value[0], 'up');
    expect(messages.value[0].feedback).toBeUndefined();
  });

  it('track 静默失败（埋点绝不抛出）', async () => {
    vi.mocked(trackEventApi).mockRejectedValue(new Error('down'));
    const { track } = useChatFeedback(ref([]));
    expect(() => track('chat.send', {})).not.toThrow();
  });

  it('限流错误落排队话术行（可重试假、无 mock 兜底）', () => {
    const messages = ref<AgentMessage[]>([]);
    const { handleStreamError } = useChatFeedback(messages);
    handleStreamError('对话过于频繁，请 1 分钟后再试', true);
    expect(messages.value).toHaveLength(1);
    expect(messages.value[0].content).toContain('排队');
    expect(messages.value[0].retryable).toBeFalsy();
  });

  it('网络错误落 mock 兜底行且 retryable', () => {
    const messages = ref<AgentMessage[]>([]);
    const { handleStreamError } = useChatFeedback(messages);
    handleStreamError('连接中断，可重试', false);
    expect(messages.value[0].retryable).toBe(true);
  });
});
