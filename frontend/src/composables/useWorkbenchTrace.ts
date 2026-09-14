// 坐席 Trace 详情（真实 /workbench/sessions/{id}/trace：会话流转态 + 消息引用 + 上下文用量）
// 与买家侧同源，坐席用于核对引用/检测卡/摘要裁剪；后端不可用回退演示种子并打 demo 标
import { ref } from 'vue';
import { toAgentMessages, traceWorkbenchApi } from '@/api';
import type { WorkbenchContext } from '@/api';
import type { AgentMessage } from '@/types/agent';
import { mockWorkbenchSeed } from '@/mock';

export const useWorkbenchTrace = () => {
  const messages = ref<AgentMessage[]>([]);
  const context = ref<WorkbenchContext | null>(null);
  const reasoning = ref('');
  const summary = ref('');
  const loading = ref(false);
  const demo = ref(false);

  const load = async (id: string) => {
    if (!id) {
      messages.value = [];
      context.value = null;
      return;
    }
    loading.value = true;
    try {
      const res = await traceWorkbenchApi({ id });
      messages.value = toAgentMessages(res?.messages ?? []);
      context.value = (res?.context ?? null) as WorkbenchContext | null;
      summary.value = String(res?.session?.resolution ?? '');
      reasoning.value = String(res?.session?.handoff_reason ?? '');
      demo.value = false;
    } catch {
      messages.value = mockWorkbenchSeed();
      context.value = null;
      summary.value = '';
      reasoning.value = '演示数据（后端 Trace 不可用）';
      demo.value = true;
    } finally {
      loading.value = false;
    }
  };

  // 本地追加（坐席代回 / AI 代答回执）：不重拉全量，避免打断坐席阅读
  const append = (message: AgentMessage) => {
    messages.value = [...messages.value, message];
  };

  return { messages, context, reasoning, summary, loading, demo, load, append };
};
