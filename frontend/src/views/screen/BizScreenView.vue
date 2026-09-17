<template>
  <div class="screen">
    <div class="head">
      <span class="hint">30秒轮询 · 缓存1分钟</span>
      <AiButton @click="load">刷新</AiButton>
    </div>
    <div class="metrics">
      <div v-for="m in metrics" :key="m.key" class="metric card" :class="m.tone">
        <span class="label">{{ m.label }}</span>
        <span class="value">{{ m.value }}</span>
      </div>
    </div>
    <div class="bottom">
      <div class="card chart">
        <h3 class="card-title">近7日 GMV 趋势</h3>
        <div class="bars">
          <div v-for="p in trend" :key="p.label" class="bar-col">
            <div class="bar" :style="{ height: `${barHeight(p.value)}px` }" />
            <span class="bar-label">{{ p.label }}</span>
          </div>
        </div>
      </div>
      <div class="card warns">
        <h3 class="card-title">异常下钻 → 补知识闭环</h3>
        <p v-for="w in warnings" :key="w.id" class="warn" :class="w.level">{{ w.content }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 经营大屏（4指标＋趋势柱＋预警下钻，30秒轮询；对齐页面设计 §3.15 与画布屏四）
import { ElMessage } from 'element-plus';
import { onMounted, onUnmounted, ref } from 'vue';
import { getScreenSummaryApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { ScreenMetric, ScreenTrendPoint, ScreenWarning } from '@/types/screen';

const POLL_MS = 30000;
const BAR_MAX_PX = 170;

const metrics = ref<ScreenMetric[]>([]);
const trend = ref<ScreenTrendPoint[]>([]);
const warnings = ref<ScreenWarning[]>([]);
let timer = 0;

const barHeight = (v: number) => {
  const max = trend.value.reduce((a, p) => Math.max(a, p.value), 1);
  return Math.round((v / max) * BAR_MAX_PX);
};

// 后端汇总直接映射到三个响应式数组，缺字段按空数组处理
const applySummary = (data: unknown) => {
  if (typeof data !== 'object' || data === null) return;
  const d = data as {
    metrics?: ScreenMetric[];
    trend?: ScreenTrendPoint[];
    warnings?: ScreenWarning[];
  };
  metrics.value = d.metrics ?? [];
  trend.value = d.trend ?? [];
  warnings.value = d.warnings ?? [];
};

const load = async () => {
  try {
    applySummary(await getScreenSummaryApi({ range: 'today' }));
  } catch (e) {
    ElMessage.error(e instanceof Error ? `加载大屏失败：${e.message}` : '加载大屏失败');
  }
};

onMounted(() => {
  load();
  timer = window.setInterval(load, POLL_MS);
});

onUnmounted(() => {
  window.clearInterval(timer);
});
</script>

<style scoped>
.screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hint {
  flex: 1;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.metrics {
  display: flex;
  gap: 12px;
}

.metric {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
}

.metric .label {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.metric .value {
  font-size: 18px;
  font-weight: 600;
  color: var(--reai-text-main);
}

.metric.good .value {
  color: var(--reai-online);
}

.metric.bad .value {
  color: var(--reai-notice);
}

.metric.warn .value {
  color: var(--reai-notice);
}

.card {
  padding: 14px 16px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
}

.card-title {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--reai-text-main);
}

.bottom {
  display: flex;
  flex: 1;
  gap: 16px;
  min-height: 0;
}

.chart {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.bars {
  display: flex;
  flex: 1;
  gap: 10px;
  align-items: flex-end;
  min-height: 0;
}

.bar-col {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  min-width: 0;
}

.bar {
  width: 100%;
  background: var(--reai-accent);
  border-radius: 6px;
  opacity: 0.75;
}

.bar-col:last-child .bar {
  opacity: 1;
}

.bar-label {
  font-size: 11px;
  color: var(--reai-text-muted);
}

.warns {
  flex: 0 1 360px;
  overflow-y: auto;
}

.warn {
  padding: 10px;
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.5;
  background: var(--reai-card);
  border-radius: 8px;
}

.warn.bad {
  background: var(--reai-notice-soft);
}

@media (width <= 1024px) {
  .metrics {
    flex-wrap: wrap;
  }

  .metric {
    flex-basis: 40%;
  }

  .bottom {
    flex-direction: column;
  }

  .warns {
    flex: none;
  }
}
</style>
