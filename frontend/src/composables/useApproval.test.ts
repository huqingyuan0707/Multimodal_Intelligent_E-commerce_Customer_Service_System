// useApproval 单测（批量空选警告 + 批量批准成功计数，对齐前端 Skill §8 改 composable 必补用例）
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { approveApprovalApi } from '@/api';
import type { ApprovalItem } from '@/types/approval';
import { useApproval } from './useApproval';

vi.mock('@/api', () => ({
  approveApprovalApi: vi.fn(),
  rejectApprovalApi: vi.fn(),
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(), prompt: vi.fn() },
}));

import { ElMessageBox } from 'element-plus';

const row = (id: string, status = 'pending'): ApprovalItem => ({
  id,
  action: 'sku.price_change',
  action_label: 'SKU 改价',
  target: 'TSIRT-001 白/M',
  args: { new_price: 11900 },
  reason: '大促报名',
  applicant: 'admin',
  approver: '',
  status,
  status_label: status === 'pending' ? '待审批' : '已通过',
  session_id: '',
  created_at: '2026-09-14 10:00:00',
  decided_at: '',
});

describe('useApproval', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('批量无待办直接警告不调接口', async () => {
    const { approveBatch } = useApproval(vi.fn());
    const ok = await approveBatch([row('a-1', 'approved')]);
    expect(ok).toBe(false);
    expect(vi.mocked(approveApprovalApi)).not.toHaveBeenCalled();
  });

  it('批量批准逐条调用并重拉列表', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue(undefined);
    vi.mocked(approveApprovalApi).mockResolvedValue({ id: 'x' });
    const reload = vi.fn();
    const { approveBatch } = useApproval(reload);
    const ok = await approveBatch([row('a-1'), row('a-2'), row('a-3', 'approved')]);
    expect(ok).toBe(true);
    expect(vi.mocked(approveApprovalApi)).toHaveBeenCalledTimes(2);
    expect(reload).toHaveBeenCalled();
  });

  it('单条批准取消确认直接返回 false', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue(new Error('cancel'));
    const { approveOne } = useApproval(vi.fn());
    const ok = await approveOne(row('a-9'));
    expect(ok).toBe(false);
    expect(vi.mocked(approveApprovalApi)).not.toHaveBeenCalled();
  });
});
