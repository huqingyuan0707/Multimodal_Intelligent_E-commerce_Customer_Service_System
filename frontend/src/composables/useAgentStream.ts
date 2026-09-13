// SSE 对话状态封装（source/phase/message/done 全分支 + 失败退避重连 3 次；主动停止不重连，对齐 API 规范 §5）
import { ref } from 'vue';
import { streamChat } from '@/api';
import type { DonePayload } from '@/api';
import type { AgentMessage } from '@/types/agent';

const MAX_RETRIES = 3;

const sleep = (ms: number): Promise<void> =>
  new Promise(resolve => {
    setTimeout(resolve, ms);
  });

export const useAgentStream = () => {
  const streaming = ref(false);
  const sources = ref<string[]>([]);
  const phase = ref('');
  const draft = ref('');
  const done = ref<DonePayload | null>(null);
  const error = ref('');
  const controller = ref<AbortController | null>(null);

  const start = async (query: string): Promise<void> => {
    streaming.value = true;
    sources.value = [];
    phase.value = '';
    draft.value = '';
    done.value = null;
    error.value = '';
    for (let attempt = 0; ; attempt += 1) {
      controller.value = new AbortController();
      await streamChat(
        query,
        {
          onSource: name => {
            if (name && !sources.value.includes(name)) {
              sources.value = [...sources.value, name];
            }
          },
          onPhase: name => {
            phase.value = name;
          },
          onMessage: content => {
            draft.value += content;
          },
          onDone: payload => {
            done.value = payload;
            streaming.value = false;
          },
          onError: msg => {
            error.value = msg;
            streaming.value = false;
          },
        },
        controller.value.signal,
      );
      if (controller.value.signal.aborted) {
        error.value = '';
        return;
      }
      if (done.value || draft.value || attempt >= MAX_RETRIES) {
        return;
      }
      // 首字未出且非主动停止：退避重连
      phase.value = `重连中…（${attempt + 1}/${MAX_RETRIES}）`;
      error.value = '';
      streaming.value = true;
      await sleep(1000 * (attempt + 1));
    }
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

  return { streaming, sources, phase, draft, done, error, start, stop, toMessage };
};
