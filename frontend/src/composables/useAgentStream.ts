// SSE 对话状态封装（source/phase/message/done 全分支 + 失败退避重连 3 次；主动停止不重连，
// 限流等 fatal 错误不重连（重连也撞墙），对齐 API 规范 §5）
import { ref } from 'vue';
import { streamChat } from '@/api';
import type { DonePayload, StreamOptions } from '@/api';

const MAX_RETRIES = 3;

const sleep = (ms: number) =>
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
  // 限流标记（fatal 错误置真）：页面显示排队话术，不本地编造回复
  const limited = ref(false);
  const controller = ref<AbortController | null>(null);

  const start = async (query: string, opts?: StreamOptions) => {
    streaming.value = true;
    sources.value = [];
    phase.value = '';
    draft.value = '';
    done.value = null;
    error.value = '';
    limited.value = false;
    for (let attempt = 0; ; attempt += 1) {
      controller.value = new AbortController();
      let fatal = false;
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
          onError: (msg, isFatal) => {
            error.value = msg;
            fatal = isFatal === true;
            if (fatal) {
              limited.value = true;
            }
            streaming.value = false;
          },
        },
        controller.value.signal,
        opts,
      );
      if (controller.value.signal.aborted) {
        error.value = '';
        return;
      }
      // 限流（2002/429）这类重连也不会好的错误：立即收手不退避
      if (fatal) {
        return;
      }
      if (done.value || draft.value || attempt >= MAX_RETRIES) {
        return;
      }
      // 首字未出且非主动停止：退避重连。草稿清零——后端按同一 clientMsgId
      // 重放全量答复（相同事件 id），不清零会把残片和重放拼成重复文本。
      draft.value = '';
      phase.value = `重连中…（${attempt + 1}/${MAX_RETRIES}）`;
      error.value = '';
      streaming.value = true;
      await sleep(1000 * (attempt + 1));
    }
  };

  const stop = () => {
    controller.value?.abort();
    streaming.value = false;
  };

  // 收尾为一条 AgentMessage（引用/trace/检测卡/上下文用量/工具调用随 done 落盘显示）
  const toMessage = (id: string) => ({
    id,
    role: 'agent' as const,
    modality: (done.value?.vision?.length ? 'image' : 'text') as 'image' | 'text',
    content: draft.value || error.value,
    references: done.value?.references ?? [],
    trace_id: done.value?.trace_id,
    // 赞踩反馈定位键随消息落盘（mining/feedback 的 message_id）
    message_id: done.value?.message_id,
    vision: done.value?.vision ?? [],
    need_human: done.value?.need_human ?? false,
    context: done.value?.context,
    // 工具透明展示：编排真调的每一步 + 中文说明（缺参/越权/回落）原样透出，前端不加工
    tool_calls: done.value?.tool_calls ?? [],
    notes: done.value?.orchestration?.notes ?? [],
  });

  return { streaming, sources, phase, draft, done, error, limited, start, stop, toMessage };
};
