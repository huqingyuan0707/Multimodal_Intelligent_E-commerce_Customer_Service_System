<template>
  <div class="page">
    <div class="head">
      <el-tag type="info" size="small">待实现页 · 画板先行（演示数据）</el-tag>
    </div>
    <div class="toolbar">
      <AiButton v-permission="['shop', 'admin']" @click="exportBill">导出对账单</AiButton>
      <AiButton v-permission="['shop', 'admin']" type="primary" @click="confirmSettle">
        日结确认
      </AiButton>
      <span class="hint">差异超阈值红字告警 · 无PII列 · 财务双人复核预留</span>
    </div>
    <el-empty v-if="!bills.length && !loading" description="暂无账单" />
    <el-table v-loading="loading" :data="bills" style="width: 100%">
      <el-table-column prop="day" label="日期" width="120" />
      <el-table-column label="应收" width="110">
        <template #default="s">{{ money(s.row.receivable) }}</template>
      </el-table-column>
      <el-table-column label="实收" width="110">
        <template #default="s">{{ money(s.row.received) }}</template>
      </el-table-column>
      <el-table-column label="退款" width="100">
        <template #default="s">{{ money(s.row.refund) }}</template>
      </el-table-column>
      <el-table-column label="差异" width="110">
        <template #default="s">
          <span :class="{ over: s.row.diff > 500 }">{{ money(s.row.diff) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="s.row.done ? 'success' : 'warning'" size="small">
            {{ s.row.done ? '已日结' : '待确认' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next, total"
      @size-change="loadBills"
      @current-change="loadBills"
    />
  </div>
</template>

<script setup lang="ts">
// 对账结算最小可用版：日结单列表 + 差异告警 + 导出 + 日结确认，对齐页面设计 §3.14
// 待实现页画板先行，财务独立角色与双人复核待B端二期补，当前店长/管理员代看
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';

type Bill = {
  day: string;
  receivable: number;
  received: number;
  refund: number;
  diff: number;
  done: boolean;
};

const bills = ref<Bill[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);

const money = (n: number) => `¥${n.toFixed(2)}`;

const loadBills = async () => {
  loading.value = true;
  try {
    bills.value = [
      {
        day: '2026-09-13',
        receivable: 124000,
        received: 121000,
        refund: 2000,
        diff: 1000,
        done: false,
      },
      {
        day: '2026-09-12',
        receivable: 98000,
        received: 97800,
        refund: 1500,
        diff: 200,
        done: true,
      },
    ];
    total.value = bills.value.length;
  } catch {
    bills.value = [];
    ElMessage.error('加载失败，请重试');
  } finally {
    loading.value = false;
  }
};

const exportBill = () => {
  ElMessage.success('对账单导出中（演示）');
};

const confirmSettle = async () => {
  await ElMessageBox.confirm('日结确认不可逆，确认今日已核对无误吗？', '提示');
  ElMessage.success('今日已日结（演示，双人复核待接）');
};

onMounted(() => {
  loadBills();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.over {
  color: var(--reai-notice);
  font-weight: 600;
}
</style>
