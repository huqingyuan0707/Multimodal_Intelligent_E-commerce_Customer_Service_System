// 采购单状态机操作（到货登记/质检；审批统一走审批中心 /approvals，采购页无直批入口；对齐页面设计 §3.12 / API 规范 §4.7）
// 从 PurchaseView 抽出复用：破坏性操作一律 confirm/prompt 前置，理由必填校验在前端先拦一道，后端 1001/3005 兜底
import { ElMessage, ElMessageBox } from 'element-plus';
import { qcPurchaseOrderApi, receivePurchaseOrderApi } from '@/api';
import type { PurchaseOrderItem } from '@/types/shop';

export const usePurchaseOps = (reload: () => unknown) => {
  // 到货登记：可回填实际到货日（YYYY-MM-DD），供客服承诺交期
  const receive = async (row: PurchaseOrderItem) => {
    let eta: string;
    try {
      ({ value: eta } = await ElMessageBox.prompt(
        '请填写实际到货日（YYYY-MM-DD，可留空沿用原预计日）',
        '到货登记',
        { inputValue: row.eta },
      ));
    } catch {
      return;
    }
    const text = (eta ?? '').trim();
    if (text && !/^\d{4}-\d{2}-\d{2}$/.test(text)) {
      ElMessage.warning('到货日格式应为 YYYY-MM-DD');
      return;
    }
    try {
      await receivePurchaseOrderApi({ id: row.id, eta: text });
      ElMessage.success('已登记到货');
      reload();
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '登记失败');
    }
  };

  // 到货质检：说明必填；合格入库 / 不合格退供（破坏性，confirm 双分支二选一）
  const qc = async (row: PurchaseOrderItem) => {
    let note: string;
    try {
      ({ value: note } = await ElMessageBox.prompt(
        '请填写质检说明（不合格需注明退供原因，必填）',
        '到货质检',
        { inputValidator: (v: string) => (v ?? '').trim().length > 0 || '质检说明必填' },
      ));
    } catch {
      return;
    }
    let passed: boolean;
    try {
      await ElMessageBox.confirm(
        `${row.id} 质检结论二选一：合格将按收货仓入库；不合格将退供（不入库，终态）`,
        '质检结论',
        {
          type: 'warning',
          distinguishCancelAndClose: true,
          confirmButtonText: '合格并入库',
          cancelButtonText: '不合格，退供',
        },
      );
      passed = true;
    } catch (action) {
      if (action === 'cancel') {
        passed = false;
      } else {
        return;
      }
    }
    try {
      await qcPurchaseOrderApi({ id: row.id, passed, note: note.trim() });
      ElMessage.success(passed ? '质检合格，已入库' : '质检不合格，已标记退供（未入库）');
      reload();
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '质检失败');
    }
  };

  return { receive, qc };
};
