// useStudioTools 单测（工具清单映射/试调参数校验/结果透出，对齐 API 规范 §4.12）
// api 层打桩；非法 JSON 与非对象参数抛中文错由页面提示
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { invokeToolApi, listToolsApi } from '@/api';
import { useStudioTools } from './useStudioTools';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, listToolsApi: vi.fn(), invokeToolApi: vi.fn() };
});

describe('useStudioTools', () => {
  beforeEach(() => vi.resetAllMocks());

  it('refresh 映射工具清单与总数', async () => {
    vi.mocked(listToolsApi).mockResolvedValue({
      total: 2,
      items: [
        {
          name: 'order.query',
          scope: 'cs',
          description: '查单',
          params: {},
          idempotent: true,
          requires_approval: false,
          approval_action: '',
          timeout_seconds: 30,
          max_retries: 3,
          breaker: {},
        },
      ],
    });
    const { tools, total, refresh } = useStudioTools();
    await refresh();
    expect(total.value).toBe(2);
    expect(tools.value.map(t => t.name)).toEqual(['order.query']);
  });

  it('trial 透出调用结果（含审批单号不吞字段）', async () => {
    vi.mocked(invokeToolApi).mockResolvedValue({
      tool: 'refund.create',
      status: 'ok',
      approval_required: true,
      approval_id: 'a-1',
    });
    const { trial } = useStudioTools();
    const result = await trial('refund.create', '{"order_id":"1"}');
    expect(result.approval_id).toBe('a-1');
    expect(vi.mocked(invokeToolApi).mock.calls[0][0]).toEqual({
      name: 'refund.create',
      args: { order_id: '1' },
    });
  });

  it('空参数文本即 {}，非法 JSON 与非对象抛中文错', async () => {
    const { trial } = useStudioTools();
    vi.mocked(invokeToolApi).mockResolvedValue({ tool: 'order.query', status: 'ok' });
    await trial('order.query', '   ');
    expect(vi.mocked(invokeToolApi).mock.calls[0][0].args).toEqual({});
    await expect(trial('order.query', '{坏')).rejects.toThrow('合法 JSON');
    await expect(trial('order.query', '[1,2]')).rejects.toThrow('JSON 对象');
  });
});
