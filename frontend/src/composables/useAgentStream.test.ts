// useAgentStream 单测（done → toMessage 透传工具调用与编排说明，对齐前端 Skill §8 改 composable 必补用例）
import { describe, expect, it, vi } from 'vitest';
import type { DonePayload } from '@/api';
import { useAgentStream } from './useAgentStream';

vi.mock('@/api', () => ({
  streamChat: vi.fn(),
}));

// done 全字段构造器：只覆盖用例关心的字段，其余按后端真实载荷补默认值
const donePayload = (patch: Partial<DonePayload> = {}): DonePayload => ({
  references: [],
  guard: { pass: true },
  faithfulness: 1,
  trace_id: 't-1',
  session_id: 's-1',
  ...patch,
});

describe('useAgentStream.toMessage', () => {
  it('done 的工具调用与编排说明透传给消息', () => {
    const { done, draft, toMessage } = useAgentStream();
    done.value = donePayload({
      tool_calls: [
        {
          tool: 'kb.retrieve',
          status: 'ok',
          scope: 'kb:read',
          idempotent: true,
          requires_approval: false,
          approval_required: false,
          args: { query: '退货政策是什么' },
          result: { total: 3, references: [{ score: 0.81 }] },
          attempts: 1,
          latency_ms: 420,
          trace_id: '8f2c1111aaaaa4d9',
        },
      ],
      orchestration: { notes: ['refund.create 未成功：缺少必填参数，已回落知识库检索'] },
    });
    draft.value = '七天无理由退货，需商品不影响二次销售。';

    const msg = toMessage('a-1');
    expect(msg.tool_calls).toHaveLength(1);
    expect(msg.tool_calls[0].tool).toBe('kb.retrieve');
    expect(msg.tool_calls[0].scope).toBe('kb:read');
    expect(msg.notes).toEqual(['refund.create 未成功：缺少必填参数，已回落知识库检索']);
    expect(msg.content).toBe('七天无理由退货，需商品不影响二次销售。');
  });

  it('重放轮无工具调用回落空数组（画板不渲染空卡）', () => {
    const { done, toMessage } = useAgentStream();
    done.value = donePayload({ tool_calls: [], orchestration: { notes: ['重放命中应答：未重跑工具调用'] } });

    const msg = toMessage('a-2');
    expect(msg.tool_calls).toEqual([]);
    expect(msg.notes).toHaveLength(1);
  });

  it('done 未到达时工具与说明均为空数组', () => {
    const { toMessage } = useAgentStream();

    const msg = toMessage('a-3');
    expect(msg.tool_calls).toEqual([]);
    expect(msg.notes).toEqual([]);
    expect(msg.references).toEqual([]);
  });
});
