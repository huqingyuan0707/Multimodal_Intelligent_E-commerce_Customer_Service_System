// 工作台右栏数据：会话级 Trace 概览（取真 trace_id 去重，不伪造规划步骤）+ 上下文用量
// 链路：WorkbenchView（/workbench/.../trace 真数据）→ 本模块 → WorkbenchSide 展示；订单卡暂无接口，保持空态
import { computed } from 'vue';
import type { Ref } from 'vue';
import type { WorkbenchContext } from '@/api';
import type { TraceRef } from '@/components/WorkbenchSide.vue';
import type { AgentMessage } from '@/types/agent';

// 右栏上下文用量（坐席判断摘要/裁剪是否发生，追问「你还记得吗」前先看这里）
export type SideUsage = {
  rounds: number;
  windowRounds: number;
  tokens: number;
  budget: number;
  dropped: number;
  ratio: number;
  hasSummary: boolean;
};

export const toSideUsage = (ctx: WorkbenchContext | null): SideUsage | null => {
  if (!ctx) {
    return null;
  }
  const budget = Number(ctx.budget ?? 0);
  const tokens = Number(ctx.tokens ?? 0);
  return {
    rounds: Number(ctx.rounds ?? 0),
    windowRounds: Number(ctx.window_rounds ?? 0),
    tokens,
    budget,
    dropped: Number(ctx.dropped ?? 0),
    ratio: budget > 0 ? Math.min(100, Math.round((tokens / budget) * 100)) : 0,
    hasSummary: Boolean(ctx.summary),
  };
};

export const useWorkbenchSide = (
  messages: Ref<AgentMessage[]>,
  context: Ref<WorkbenchContext | null>,
) => {
  // 本轮 Trace 概览：坐席看过程（trace_id 去重）
  const sessionTraces = computed<TraceRef[]>(() => {
    const seen: string[] = [];
    const out: TraceRef[] = [];
    messages.value.forEach(m => {
      const id = m.trace_id ?? '';
      if (id && !seen.includes(id)) {
        seen.push(id);
        out.push({ id, summary: (m.content ?? '').slice(0, 14) || '流式回复' });
      }
    });
    return out;
  });
  const sideUsage = computed(() => toSideUsage(context.value));
  return { sessionTraces, sideUsage };
};
