// useWorkbenchSide 单测（演示订单挂标 + Trace 去重 + 空摘要兜底 + 上下文用量折算，对齐前端 Skill §8）
import { ref } from 'vue';
import { describe, expect, it } from 'vitest';
import type { WorkbenchContext } from '@/api';
import type { AgentMessage } from '@/types/agent';
import { useWorkbenchSide } from './useWorkbenchSide';

const msg = (id: string, trace?: string, content = '答复内容示例文本填充'): AgentMessage => ({
  id,
  role: 'agent',
  modality: 'text',
  content,
  trace_id: trace,
});

const ctx = (patch: Partial<WorkbenchContext>): WorkbenchContext => ({
  summary: '',
  rounds: 0,
  tokens: 0,
  dropped: 0,
  budget: 0,
  window_rounds: 0,
  ...patch,
});

describe('useWorkbenchSide', () => {
  it('演示订单带 demo 旗标', () => {
    const { sideOrder, sideDemo } = useWorkbenchSide(ref([]), ref(null));
    expect(sideOrder.value.no).toBe('2024091400821');
    expect(sideDemo.value).toBe(true);
  });

  it('Trace 按 trace_id 去重并截摘要', () => {
    const messages = ref([
      msg('a-1', 'tr-1', '袖口脱线约2cm可换货处理'),
      msg('a-2', 'tr-1'),
      msg('a-3'),
    ]);
    const { sessionTraces } = useWorkbenchSide(messages, ref(null));
    expect(sessionTraces.value).toHaveLength(1);
    expect(sessionTraces.value[0]?.summary).toBe('袖口脱线约2cm可换货处理'.slice(0, 14));
  });

  it('无内容 Trace 兜底流式回复', () => {
    const messages = ref([msg('a-1', 'tr-9', '')]);
    const { sessionTraces } = useWorkbenchSide(messages, ref(null));
    expect(sessionTraces.value[0]?.summary).toBe('流式回复');
  });

  it('上下文用量按 tokens/budget 折算比例并标注摘要', () => {
    const messages = ref<AgentMessage[]>([]);
    const context = ref<WorkbenchContext | null>(
      ctx({ summary: '已摘要', rounds: 4, window_rounds: 6, tokens: 1500, budget: 3000, dropped: 2 }),
    );
    const { sideUsage } = useWorkbenchSide(messages, context);
    expect(sideUsage.value).toEqual({
      rounds: 4,
      windowRounds: 6,
      tokens: 1500,
      budget: 3000,
      dropped: 2,
      ratio: 50,
      hasSummary: true,
    });
  });

  it('预算为 0 时比例归零；无上下文时用量为空（右栏空态）', () => {
    const context = ref<WorkbenchContext | null>(ctx({ tokens: 120 }));
    expect(useWorkbenchSide(ref([]), context).sideUsage.value?.ratio).toBe(0);
    expect(useWorkbenchSide(ref([]), ref(null)).sideUsage.value).toBeNull();
  });
});
