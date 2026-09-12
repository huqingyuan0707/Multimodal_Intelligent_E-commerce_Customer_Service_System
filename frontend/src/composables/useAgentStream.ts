// SSE 对话状态封装（调用 api.streamChat，页面只做编排，对齐 API 规范 §5）
import { ref } from 'vue';
import { streamChat } from '@/api';
import type { DonePayload } from '@/api';
import type { AgentMessage } from '@/types/agent';

export const useAgentStream = () => {
  const streaming = ref(false);
  const phase = ref('');
  const draft = ref('');
  const done = ref<DonePayload | null>(null);
  const error = ref('');
  const controller = ref<AbortController | null>(null);

  const start = async (query: string): Promise<void> => {
    streaming.value = true;
    phase.value = '';
    draft.value = '';
    done.value = null;
    error.value = '';
    controller.value = new AbortController();
    await streamChat(
      query,
      {
        onPhase: (name) => {
          phase.value = name;
        },
        onMessage: (content) => {
          draft.value += content;
        },
        onDone: (payload) => {
          done.value = payload;
          streaming.value = false;
        },
        onError: (msg) => {
          error.value = msg;
          streaming.value = false;
        },
      },
      controller.value.signal,
    );
  };

  const stop = (): void => {
    controller.value?.abort();
    streaming.value = false;
  };

  // 收尾为一条 AgentMessage（引用/trace 随 done 落盘显示）
  const toMessage = (id: string): AgentMessage => ({
    id,
    role: 'agent',
    modality: 'text',
    content: draft.value || error.value,
    references: done.value?.references ?? [],
    trace_id: done.value?.trace_id,
  });

  return { streaming, phase, draft, done, error, start, stop, toMessage };
};
