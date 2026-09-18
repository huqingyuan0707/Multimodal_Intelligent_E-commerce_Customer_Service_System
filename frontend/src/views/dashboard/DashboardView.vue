<template>
  <div class="page">
    <div class="head">
      <span v-if="llmHint" class="hint">{{ llmHint }}</span>
      <el-select v-model="range" size="small" class="range" @change="onRange">
        <el-option label="今日" value="today" />
        <el-option label="近7日" value="week" />
      </el-select>
      <AiButton @click="reload">刷新</AiButton>
    </div>
    <div class="cards">
      <el-card v-for="m in metrics" :key="m.key" v-loading="loading" class="card">
        <div class="card-top">
          <span class="label">{{ m.label }}</span>
          <el-tag v-if="m.overBudget" type="danger" size="small">超预算</el-tag>
        </div>
        <div class="value" :class="{ 'val-flash': changedKeys.includes(m.key) }">{{ m.value }}</div>
        <div class="desc">{{ m.desc }}</div>
      </el-card>
    </div>
    <el-card class="trend">
      <template #header>
        <span>问答轮次趋势（{{ range === 'week' ? '近7日按天' : '今日按小时' }}）</span>
      </template>
      <el-empty
        v-if="!trend.length && !loading"
        description="暂无趋势数据，有问答后按小时/按天出柱"
      />
      <div v-else v-loading="loading" class="bars">
        <div v-for="p in trend" :key="p.label" class="bar-col">
          <div class="bar" :style="{ height: `${barHeight(p.value)}px` }" />
          <span class="bar-label">{{ p.label }}</span>
        </div>
      </div>
    </el-card>
    <h3>最慢链路 Top5（点击跳转坐席工作台查看详情）</h3>
    <el-empty v-if="!topTraces.length && !loading" description="暂无慢链路记录" />
    <el-table v-loading="loading" :data="topTraces" class="table">
      <el-table-column label="trace_id" min-width="160">
        <template #default="s">
          <span class="mono">{{ s.row.trace }}</span>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="110">
        <template #default="s">{{ formatLatency(s.row.latencyMs) }}</template>
      </el-table-column>
      <el-table-column prop="tenant" label="租户" min-width="140" />
      <el-table-column label="渠道" width="110">
        <template #default="s">{{ channelLabelOf(s.row.channel) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="s">
          <AiButton link size="small" @click="goTrace(s.row.trace)">跳转详情</AiButton>
          <AiButton link type="primary" size="small" @click="copyTrace(s.row.trace)">
            复制
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
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
          <AiButton link type="primary" size="small" @click="copyTrace(s.row.slowTraceId)">
            复制
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
</template>

<script setup lang="ts">
// 数据看板：指标卡 + 趋势 + 慢 Trace + 按租户/渠道归因表（对齐页面设计 §3.7）
import {
  ElCard,
  ElEmpty,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getDashboardSummaryApi, getGovernanceStatusApi } from '@/api';
import type { DashboardSlowTrace, DashboardTrendPoint } from '@/api/dashboard';
import AiButton from '@/shared/components/AiButton.vue';
import { channelLabelOf, formatCost, formatLatency } from '@/types/dashboard';
import type { AttributionRow, DashboardMetric } from '@/types/dashboard';

type SlowTrace = {
  trace: string;
  tenant: string;
  channel: string;
  latencyMs: number;
};

const BAR_MAX_PX = 120;
const router = useRouter();

const metrics = ref<DashboardMetric[]>([]);
const trend = ref<DashboardTrendPoint[]>([]);
const slowList = ref<DashboardSlowTrace[]>([]);
const rows = ref<AttributionRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const range = ref('today');
const loading = ref(false);
const llmHint = ref('');
// 指标值变化闪光：刷新后数值变化的卡片提示一次
const changedKeys = ref<string[]>([]);
let changedTimer = 0;

const loadGov = async () => {
  try {
    const g = await getGovernanceStatusApi();
    const ok = g?.llm?.available;
    llmHint.value = ok ? '模型服务在线' : '模型服务不可用，问答将降级';
  } catch {
    llmHint.value = '模型状态未知';
  }
};

const load = async () => {
  loading.value = true;
  try {
    const res = await getDashboardSummaryApi({
      page: page.value,
      size: size.value,
      range: range.value,
    });
    const next = Array.isArray(res.metrics) ? res.metrics : [];
    changedKeys.value = next
      .filter(n => {
        const prev = metrics.value.find(m => m.key === n.key);
        return prev && prev.value !== n.value;
      })
      .map(n => n.key);
    window.clearTimeout(changedTimer);
    changedTimer = window.setTimeout(() => {
      changedKeys.value = [];
    }, 800);
    metrics.value = next;
    trend.value = Array.isArray(res.trend) ? res.trend : [];
    slowList.value = Array.isArray(res.slow_traces) ? res.slow_traces : [];
    rows.value = Array.isArray(res.items) ? res.items : [];
    total.value = typeof res.total === 'number' ? res.total : 0;
  } catch {
    metrics.value = [];
    trend.value = [];
    slowList.value = [];
    rows.value = [];
    total.value = 0;
    ElMessage.error('看板数据加载失败，请稍后重试');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
  loadGov();
};

const onRange = () => {
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

const copyTrace = async (traceId: string) => {
  try {
    await navigator.clipboard.writeText(traceId);
    ElMessage.success('trace_id 已复制');
  } catch {
    ElMessage.error('复制失败，请手动记录');
  }
};

// 趋势柱高：按最大值归一到 BAR_MAX_PX（与经营大屏同算法）
const barHeight = (v: number) => {
  const max = trend.value.reduce((a, p) => Math.max(a, p.value), 1);
  return Math.round((v / max) * BAR_MAX_PX);
};

// 慢 Trace Top5：优先服务端 tool_calls 实测排序；缺失时从归因行 slowTraceId 兜底
const topTraces = computed<SlowTrace[]>(() => {
  if (slowList.value.length) {
    return slowList.value.slice(0, 5).map(t => ({
      trace: t.trace_id,
      tenant: '',
      channel: '',
      latencyMs: t.latency_ms,
    }));
  }
  const seen: string[] = [];
  const out: SlowTrace[] = [];
  rows.value.forEach(r => {
    const t = String(r.slowTraceId ?? '');
    if (t && t !== '—' && !seen.includes(t) && out.length < 5) {
      seen.push(t);
      out.push({ trace: t, tenant: r.tenant, channel: r.channel, latencyMs: 0 });
    }
  });
  return out;
});

const goTrace = async (traceId: string) => {
  try {
    await navigator.clipboard.writeText(traceId);
    ElMessage.success('trace_id 已复制并跳转');
  } catch {
    ElMessage.warning('复制失败，已直接跳转，可手动记录 trace_id');
  }
  router.push({ path: '/workbench', query: { trace: traceId } });
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

/* 目的性动效：刷新后数值变化的指标闪光一次 */
@keyframes val-flash-in {
  0% {
    color: var(--reai-accent);
  }

  100% {
    color: var(--reai-text-main);
  }
}

.val-flash {
  animation: val-flash-in 0.8s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .val-flash {
    animation: none;
  }
}

.desc {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.trend {
  width: 100%;
}

.range {
  width: 100px;
}

.bars {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  min-height: 120px;
}

.bar-col {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  min-width: 0;
}

.bar {
  width: 100%;
  min-height: 2px;
  background: var(--reai-accent);
  border-radius: 4px;
  opacity: 0.75;
}

.bar-col:last-child .bar {
  opacity: 1;
}

.bar-label {
  font-size: 11px;
  color: var(--reai-text-muted);
  white-space: nowrap;
}

.table {
  width: 100%;
}

.mono {
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-caption);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
