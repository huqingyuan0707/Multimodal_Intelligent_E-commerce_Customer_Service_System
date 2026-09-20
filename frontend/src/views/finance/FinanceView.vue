<template>
  <div class="page">
    <!-- 日结单（对齐画板 fin-bill：应收/实收/退款/运费/扣点 + 差异超阈值红字；服务端分页 默认20） -->
    <div class="card">
      <div class="filters">
        <el-date-picker
          v-model="bizDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="账期日"
          class="date"
        />
        <AiButton @click="reload">查询</AiButton>
        <AiButton @click="exportCsv">导出本页</AiButton>
        <span class="hint">
          待结算 {{ unsettled }} 张 · 差异告警阈值
          {{ formatCents(diffWarnCents) }}（服务端下发口径）
        </span>
      </div>
      <el-table v-loading="loading" :data="rows" class="table">
        <el-table-column prop="biz_date" label="账期日" width="110" />
        <el-table-column label="应收" width="100">
          <template #default="s">{{ formatCents(s.row.receivable) }}</template>
        </el-table-column>
        <el-table-column label="实收" width="100">
          <template #default="s">{{ formatCents(s.row.received) }}</template>
        </el-table-column>
        <el-table-column label="退款" width="100">
          <template #default="s">{{ formatCents(s.row.refund) }}</template>
        </el-table-column>
        <el-table-column label="运费" width="90">
          <template #default="s">{{ formatCents(s.row.freight) }}</template>
        </el-table-column>
        <el-table-column label="扣点" width="90">
          <template #default="s">{{ formatCents(s.row.fee) }}</template>
        </el-table-column>
        <el-table-column label="应到账" width="100">
          <template #default="s">{{ formatCents(s.row.expected) }}</template>
        </el-table-column>
        <el-table-column label="差异" width="130">
          <template #default="s">
            <span :class="{ 'diff-warn': s.row.diff_warn }">
              {{ (s.row.diff > 0 ? '+' : '') + formatCents(s.row.diff) }}
            </span>
            <el-tag v-if="s.row.diff_warn" type="warning" size="small">超阈值</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="日结状态" width="100">
          <template #default="s">
            <el-tag
              :type="s.row.settled ? 'success' : s.row.settled_by ? 'warning' : 'info'"
              size="small"
            >
              {{ s.row.settled ? '已结清' : s.row.settled_by ? '待复核' : '未制单' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="制单人" width="95">
          <template #default="s">{{ s.row.settled_by || '—' }}</template>
        </el-table-column>
        <el-table-column label="复核人" width="95">
          <template #default="s">{{ s.row.reviewed_by || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="s">
            <!-- 双人复核两步：未制单→制单；已制单未复核→换人复核结清（同人后端 1001 兜底） -->
            <AiButton
              v-if="!s.row.settled_by && !s.row.settled"
              v-permission="['shop', 'admin']"
              link
              type="primary"
              size="small"
              @click="settle(s.row as FinanceBillItem)"
            >
              制单
            </AiButton>
            <AiButton
              v-else-if="!s.row.settled"
              v-permission="['shop', 'admin']"
              link
              type="warning"
              size="small"
              @click="review(s.row as FinanceBillItem)"
            >
              复核结清
            </AiButton>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          :current-page="page"
          :page-size="size"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="sizes, prev, pager, next, total"
          @current-change="onPage"
          @size-change="onSize"
        />
      </div>
    </div>

    <!-- 双人复核（对齐画板 fin-settle：制单+复核分开，换人复核才结清；无 PII 列） -->
    <div class="card settle-card">
      <span class="hint">
        日结两步走（双人复核）：先「制单」落制单人，再由**另一账号**「复核结清」才算已结算；
        制单人与复核人不能为同一人，两步均不可逆、后端审计留痕。
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
// 对账结算：日结单列表（差异公式/阈值由服务端下发）+ 导出本页 CSV + 日结确认
// 对齐页面设计 §3.14 / 画板 对账结算-/finance；金额一律分，展示走 formatCents，前端禁硬编码金额口径
import {
  ElDatePicker,
  ElMessage,
  ElMessageBox,
  ElPagination,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import { listBillsApi, settleBillApi, confirmSettleBillApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { FinanceBillItem } from '@/types/shop';
import { formatCents } from '@/types/shop';

const rows = ref<FinanceBillItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const bizDate = ref('');
const loading = ref(false);
const diffWarnCents = ref(0);
const unsettled = ref(0);

const load = async () => {
  loading.value = true;
  try {
    const res = await listBillsApi({
      biz_date: bizDate.value ?? '',
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    diffWarnCents.value = res.diff_warn_cents ?? 0;
    unsettled.value = res.unsettled ?? 0;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载日结单失败：${e.message}` : '加载日结单失败');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
};

const onPage = (p: number) => {
  page.value = p;
  load();
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  load();
};

// 日结制单（第一步，破坏性：confirm 后不可逆，重复制单后端 1001 兜底）
const settle = async (row: FinanceBillItem) => {
  try {
    await ElMessageBox.confirm(
      `确认对 ${row.biz_date} 日结制单？制单后需另一账号复核才结清。`,
      '日结制单',
      { type: 'warning' },
    );
  } catch {
    return;
  }
  try {
    await settleBillApi({ biz_date: row.biz_date });
    ElMessage.success(`${row.biz_date} 已制单，待复核`);
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '日结制单失败');
  }
};

// 日结复核（第二步，换人复核通过才结清；与制单人同账号时后端 1001 红线兜底）
const review = async (row: FinanceBillItem) => {
  try {
    await ElMessageBox.confirm(
      `确认复核 ${row.biz_date} 日结单并结清？制单人为 ${row.settled_by}，复核后不可逆。`,
      '日结复核',
      { type: 'warning' },
    );
  } catch {
    return;
  }
  try {
    await confirmSettleBillApi({ biz_date: row.biz_date });
    ElMessage.success(`${row.biz_date} 已复核结清`);
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '日结复核失败');
  }
};

// 导出本页 CSV（BOM 保证 Excel 打开不乱码；数据全部来自当前页真实接口数据）
const exportCsv = () => {
  const header = [
    '账期日',
    '应收(分)',
    '实收(分)',
    '退款(分)',
    '运费(分)',
    '扣点(分)',
    '应到账(分)',
    '差异(分)',
    '超阈值',
    '日结状态',
    '制单人',
    '复核人',
  ];
  const lines = rows.value.map(row =>
    [
      row.biz_date,
      row.receivable,
      row.received,
      row.refund,
      row.freight,
      row.fee,
      row.expected,
      row.diff,
      row.diff_warn ? '是' : '否',
      row.settled ? '已结清' : row.settled_by ? '待复核' : '未制单',
      row.settled_by || '',
      row.reviewed_by || '',
    ].join(','),
  );
  const blob = new Blob([`\ufeff${[header.join(','), ...lines].join('\n')}`], {
    type: 'text/csv;charset=utf-8',
  });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `finance-bills-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

onMounted(() => {
  load();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.card {
  background: var(--reai-bg-container);
  border-radius: 12px;
  padding: 16px;
}

.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.date {
  width: 150px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.table {
  width: 100%;
}

/* 差异超阈值红字（画板 fin-b1w 规格：#D97706 语义落在 --reai-notice） */
.diff-warn {
  font-weight: 600;
  color: var(--reai-notice);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.settle-card {
  background: var(--reai-notice-soft);
}
</style>
