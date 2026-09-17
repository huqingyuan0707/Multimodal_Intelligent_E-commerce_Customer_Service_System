// useChatSend 单测（t- 占位不传 threadId、clientMsgId 幂等、done 认领、错误两种收尾、重试过滤，
// 对齐前端 Skill §8 改 composable 必补用例）。deps 全注入假对象，不依赖网络与真实 stream。
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import type { AgentMessage } from '@/types/agent';
import { useChatSend } from './useChatSend';
import type { SendDeps } from './useChatSend';

const fakeStream = (behavior: 'ok' | 'error' | 'limited' = 'ok') => ({
  streaming: ref(false),
  error: ref(''),
  limited: ref(false),
  done: ref<{ session_id?: string } | null>(null),
  start: vi.fn(async () => {
    if (behavior === 'error') {
      fakeStreamInstance.error.value = '连接中断，可重试';
      return;
    }
    if (behavior === 'limited') {
      fakeStreamInstance.error.value = '对话过于频繁，请 1 分钟后再试';
      fakeStreamInstance.limited.value = true;
      return;
    }
    fakeStreamInstance.done.value = { session_id: 's-9' };
  }),
  toMessage: (id: string) => ({
    id,
    role: 'agent' as const,
    modality: 'text' as const,
    content: '支持 7 天无理由退货',
    references: [],
  }),
});
let fakeStreamInstance: ReturnType<typeof fakeStream>;

const deps = (behavior: 'ok' | 'error' | 'limited' = 'ok') => {
  fakeStreamInstance = fakeStream(behavior);
  const messages = ref<AgentMessage[]>([]);
  return {
    messages,
    input: ref('退货政策'),
    stream: fakeStreamInstance,
    feedback: { track: vi.fn(), handleStreamError: vi.fn() },
    upload: {
      images: ref([]),
      uploadAll: vi.fn(async () => []),
      clear: vi.fn(),
    },
    stickNow: vi.fn(),
    getFollowups: () => ['换货要几天'],
  } as unknown as SendDeps;
};

describe('useChatSend', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('send 成功：用户泡+Agent 泡落条，t- 占位不传 threadId 且 done 后认领', async () => {
    const d = deps('ok');
    const { send } = useChatSend(d);
    d.input.value = '退货政策';
    await send();
    expect(d.stream.start).toHaveBeenCalledWith(
      '退货政策',
      expect.objectContaining({ threadId: undefined, clientMsgId: expect.stringMatching(/^c-/) }),
    );
    const roles = d.messages.value.map(m => m.role);
    expect(roles).toEqual(['user', 'agent']);
    expect(d.messages.value[1].followups).toEqual(['换货要几天']);
    expect(d.feedback.track).toHaveBeenCalledWith(
      'chat.send',
      expect.objectContaining({ len: 4, images: 0 }),
    );
  });

  it('send 网络错误：交 handleStreamError（fatal=false），不落 Agent 泡', async () => {
    const d = deps('error');
    const { send } = useChatSend(d);
    await send();
    expect(d.feedback.handleStreamError).toHaveBeenCalledWith('连接中断，可重试', false);
    expect(d.messages.value.map(m => m.role)).toEqual(['user']);
  });

  it('send 限流：fatal=true 透传（页面显示排队话术不走 mock）', async () => {
    const d = deps('limited');
    const { send } = useChatSend(d);
    await send();
    expect(d.feedback.handleStreamError).toHaveBeenCalledWith(
      expect.stringContaining('频繁'),
      true,
    );
  });

  it('retry 复用同一 clientMsgId 且先清掉可重试错误行', async () => {
    const d = deps('ok');
    const { send, retry } = useChatSend(d);
    await send();
    const startMock = d.stream.start as unknown as ReturnType<typeof vi.fn>;
    const firstCall = startMock.mock.calls[0][1] as { clientMsgId: string };
    d.messages.value.push({
      id: 'x',
      role: 'agent',
      modality: 'text',
      content: 'mock',
      retryable: true,
    });
    await retry();
    const secondCall = startMock.mock.calls[1][1] as { clientMsgId: string };
    expect(secondCall.clientMsgId).toBe(firstCall.clientMsgId);
    expect(d.messages.value.some(m => m.retryable)).toBe(false);
  });

  it('noticeLine 追加系统提示行并埋点', () => {
    const d = deps('ok');
    const { noticeLine } = useChatSend(d);
    noticeLine('退换申请已提交，待客服确认');
    expect(d.messages.value[0].content).toContain('退换申请');
    expect(d.feedback.track).toHaveBeenCalledWith('quick.notice', {});
  });
});
