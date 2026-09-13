<template>
  <div class="page">
    <div class="head">
      <h2>数据看板</h2>
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
      <span v-if="llmHint" class="hint">{{ llmHint }}</span>
      <AiButton @click="reload">刷新</AiButton>
    </div>
    <div class="cards">
      <el-card v-for="m in metrics" :key="m.key" v-loading="loading" class="card">
        <div class="card-top">
          <span class="label">{{ m.label }}</span>
          <el-tag v-if="m.overBudget" type="danger" size="small">超预算</el-tag>
        </div>
        <div class="value">{{ m.value }}</div>
        <div class="desc">{{ m.desc }}</div>
      </el-card>
    </div>
    <el-card class="trend">
      <template #header>
        <span>趋势图</span>
      </template>
      <el-empty description="趋势图后续补（P2 接大屏汇总）" />
    </el-card>
    <h3>按租户 / 渠道归因</h3>
    <el-table v-loading="loading" :data="rows" class="table">
      <el-table-column prop="tenant" label="租户" min-width="140" />
      <el-table-column label="渠道" width="110">
        <template #default="s">{{ channelLabelOf(s.row.channel) }}</template>
      </el-table-column>
      <el-table-column prop="sessions" label="会话量" width="100" />
      <el-table-column prop="resolveRate" label="解决率" width="100" />
      <el-table-column label="Token 成本" width="120">
        <template #default="s">{{ formatCost(s.row.costCents) }}</template>
      </el-table-column>
      <el-table-column label="预算" width="100">
        <template #default="s">
          <el-tag :type="s.row.overBudget ? 'danger' : 'success'" size="small">
            {{ s.row.overBudget ? '超预算' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="慢 Trace" min-width="180">
        <template #default="s">
          <span class="mono">{{ s.row.slowTraceId }}</span>
          <el-button link type="primary" size="small" @click="copyTrace(s.row.slowTraceId)">
            复制
          </el-button>
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
</template>

<script setup lang="ts">
// 数据看板：指标卡 + 按租户/渠道归因表框架（趋势图与慢 Trace 下钻后续补，对齐页面设计 §3.7）
import { ElButton, ElCard, ElEmpty, ElMessage, ElPagination, ElTable, ElTableColumn, ElTag } from 'element-plus';
import { onMounted, ref } from 'vue';
import { getGovernanceStatusApi, listAttributionApi } from '@/api';
import { mockAttributions, mockMetrics } from '@/mock/dashboard';
import AiButton from '@/shared/components/AiButton.vue';
import { channelLabelOf, formatCost } from '@/types/dashboard';
import type { AttributionRow, DashboardMetric } from '@/types/dashboard';

const metrics = ref<DashboardMetric[]>([]);
const rows = ref<AttributionRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
const demo = ref(false);
const llmHint = ref('');

const loadGov = async () => {
  try {
    const g = await getGovernanceStatusApi();
    const ok = g?.llm?.available;
    llmHint.value = ok ? '模型服务在线' : '模型服务不可用，问答将降级';
  } catch {
    llmHint.value = '模型状态未知（演示）';
  }
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listAttributionApi({ page: page.value, size: size.value });
    metrics.value = Array.isArray(res.metrics) ? res.metrics : mockMetrics;
    rows.value = Array.isArray(res.items) ? res.items : mockAttributions;
    total.value = typeof res.total === 'number' ? res.total : mockAttributions.length;
    demo.value = false;
  } catch {
    metrics.value = mockMetrics;
    const start = (page.value - 1) * size.value;
    rows.value = mockAttributions.slice(start, start + size.value);
    total.value = mockAttributions.length;
    demo.value = true;
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
  loadGov();
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

const copyTrace = async (traceId: string) => {
  try {
    await navigator.clipboard.writeText(traceId);
    ElMessage.success('trace_id 已复制');
  } catch {
    ElMessage.error('复制失败，请手动记录');
  }
};

onMounted(() => {
  load();
  loadGov();
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
  gap: 12px;
  align-items: center;
}

.head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--reai-text-main);
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.label {
  font-size: 13px;
  color: var(--reai-text-muted);
}

.value {
  margin: 8px 0 4px;
  font-size: 22px;
  color: var(--reai-text-main);
}

.desc {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.trend {
  width: 100%;
}

.table {
  width: 100%;
}

.mono {
  font-family: monospace;
  font-size: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
