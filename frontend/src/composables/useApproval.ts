// 审批操作封装（确认框 + 幂等批/驳/改参批准，对齐页面设计 §3.4 + 前端 Skill §4）
// 页面只做编排：表格选中 + 列表重拉留在 View，本模块只管“问一句再调接口并给中文反馈”。
import { ElMessage, ElMessageBox } from 'element-plus';
import { approveApprovalApi, rejectApprovalApi } from '@/api';
import type { ApprovalItem } from '@/types/approval';

export const useApproval = (reload: () => unknown) => {
  // 单条批准：先 confirm（破坏性二次确认），成功后重拉列表
  const approveOne = async (row: ApprovalItem) => {
    try {
      await ElMessageBox.confirm(
        `批准「${row.action_label}｜${row.target}」并立即生效吗？`,
        '批准确认'
      );
    } catch {
      return false;
    }
    try {
      await approveApprovalApi({ id: row.id });
      ElMessage.success('审批已通过并生效');
      reload();
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '批准失败');
      return false;
    }
  };

  // 改参批准：审批人改金额/参数后再批（如 11900 改成 12900，注意单位为分）
  const approveWithArgs = async (row: ApprovalItem) => {
    let raw = '';
    try {
      const ret = await ElMessageBox.prompt('改后参数（JSON，可空则直接批准）', '改参批准', {
        inputValue: JSON.stringify(row.args ?? {}),
      });
      raw = ret.value;
    } catch {
      return false;
    }
    let modified: object = {};
    if (raw.trim()) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (typeof parsed !== 'object' || parsed === null) {
          throw new Error('not object');
        }
        modified = parsed;
      } catch {
        ElMessage.warning('参数不是合法 JSON 对象');
        return false;
      }
    }
    try {
      await approveApprovalApi({ id: row.id, modifiedArgs: modified });
      ElMessage.success('已按改后参数批准并生效');
      reload();
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '批准失败');
      return false;
    }
  };

  // 单条驳回：理由必填并留痕（后端追加“驳回原因”，账不动）
  const rejectOne = async (row: ApprovalItem) => {
    let reason = '';
    try {
      const ret = await ElMessageBox.prompt('驳回理由（必填，留痕）', '驳回');
      reason = ret.value;
    } catch {
      return false;
    }
    if (!reason.trim()) {
      ElMessage.warning('驳回理由必填');
      return false;
    }
    try {
      await rejectApprovalApi({ id: row.id, reason: reason.trim() });
      ElMessage.success('已驳回，原数据保持不变');
      reload();
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '驳回失败');
      return false;
    }
  };

  // 批量批准：仅待办可批，逐条幂等调用（后端无批量端点，前端循环即批量语义）
  const approveBatch = async (rows: ApprovalItem[]) => {
    const targets = rows.filter(r => r.status === 'pending');
    if (!targets.length) {
      ElMessage.warning('所选无待审批单');
      return false;
    }
    try {
      await ElMessageBox.confirm(`批量批准 ${targets.length} 单并立即生效吗？`, '批量批准');
    } catch {
      return false;
    }
    let okCount = 0;
    for (const r of targets) {
      try {
        await approveApprovalApi({ id: r.id });
        okCount += 1;
      } catch {
        // 单条失败不中断：最后统一提示成功数，失败单留在待办可重试
      }
    }
    ElMessage.success(`批量批准完成：成功 ${okCount}/${targets.length}`);
    reload();
    return okCount === targets.length;
  };

  return { approveOne, approveWithArgs, rejectOne, approveBatch };
};
