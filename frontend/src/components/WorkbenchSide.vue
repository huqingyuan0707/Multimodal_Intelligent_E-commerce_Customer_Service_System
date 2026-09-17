<template>
  <div class="side">
    <div class="card">
      <h3 class="card-title">当前订单</h3>
      <el-empty v-if="!order" description="暂无关联订单" />
      <template v-else>
        <p class="kv">订单号：{{ order.no }}</p>
        <p class="kv">
          状态：<span class="warn">{{ order.status }}</span>
        </p>
        <p class="kv">
          实付金额：<span class="money">{{ order.amount }}</span>
        </p>
      </template>
    </div>
    <div class="card">
      <h3 class="card-title">本轮 Trace（会话级概览）</h3>
      <el-empty v-if="!traces.length" description="本会话暂无 Trace（发送消息后产生）" />
      <p v-for="t in traces" :key="t.id" class="kv">
        <span class="mono">{{ t.id }}</span>
        <span class="tsum">{{ t.summary }}</span>
        <AiButton link size="small" @click="copyTrace(t.id)">复制</AiButton>
      </p>
    </div>
    <div class="card">
      <h3 class="card-title">上下文用量</h3>
      <el-empty v-if="!usage" description="暂无用量（接口返回后展示）" :image-size="48" />
      <template v-else>
        <p class="kv">
          轮次：<span class="mono">{{ usage.rounds }}</span> / 窗口 {{ usage.windowRounds }}
        </p>
        <p class="kv">
          Token：<span class="mono">{{ usage.tokens }}</span> / 预算 {{ usage.budget }}
        </p>
        <p class="kv">
          摘要：<span :class="usage.hasSummary ? 'ok' : 'warn'">{{
            usage.hasSummary ? '已生成' : '未生成'
          }}</span>
          <span class="tsum">裁剪 {{ usage.dropped }} 次</span>
        </p>
        <div class="bar"><i :style="{ width: `${usage.ratio}%` }" /></div>
      </template>
    </div>
    <div class="card grow-card">
      <h3 class="card-title">AI 辅助 / 会话洞察</h3>
      <p class="hint">识别到「售后/退款」意图，建议先核对订单状态。</p>
      <p class="sub">推荐回复</p>
      <button v-for="r in suggestions" :key="r" class="suggest" @click="fill(r)">
        {{ r }}
      </button>
    </div>
    <!-- 父级注入内部备注卡（坐席协作信息，不参与买家侧消息流） -->
    <slot />
  </div>
</template>

<script setup lang="ts">
// 右栏：订单卡（父传，缺省空态）＋本轮 Trace 概览（取真 trace_id）＋上下文用量（真 /trace 口径）
// ＋AI 辅助（推荐回复点选填入）＋备注插槽；对齐画布 sidePanel 与页面设计 §3.2
import { ElMessage } from 'element-plus';
import AiButton from '@/shared/components/AiButton.vue';
import type { SideUsage } from '@/composables/useWorkbenchSide';

export type SideOrder = {
  no: string;
  status: string;
  amount: string;
};

export type TraceRef = {
  id: string;
  summary: string;
};

defineProps<{
  order?: SideOrder | null;
  traces: TraceRef[];
  usage: SideUsage | null;
}>();
const emit = defineEmits(['fill']);

const suggestions = [
  '您的订单已在打包中，预计今日 18:00 前发出。',
  '如需修改地址，请在发货前告知，我帮您申请。',
];

const fill = (text: string) => {
  emit('fill', text);
};

const copyTrace = async (id: string) => {
  try {
    await navigator.clipboard.writeText(id);
    ElMessage.success('trace_id 已复制');
  } catch {
    ElMessage.error('复制失败，请手动记录');
  }
};
</script>

<style scoped>
.side {
  display: flex;
  flex: 0 1 300px;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.card {
  padding: 16px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}

.card-title {
  margin: 0;
  font-size: var(--reai-fs-title);
  font-weight: var(--reai-fw-semibold);
  line-height: var(--reai-lh-tight);
  color: var(--reai-text-main);
}

.kv {
  margin: 8px 0;
  font-size: var(--reai-fs-body-sm);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-main);
}

.warn {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-notice);
}

.ok {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-online);
}

.bar {
  height: 6px;
  margin-top: 8px;
  overflow: hidden;
  background: var(--reai-card-2);
  border-radius: 999px;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--reai-primary);
}

.mono {
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-micro);
}

.tsum {
  margin-left: 6px;
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-muted);
}

.money {
  font-weight: 600;
  color: var(--reai-notice);
}

.grow-card {
  flex: 1;
  overflow-y: auto;
}

.hint {
  padding: 12px;
  font-size: var(--reai-fs-caption);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-soft);
  background: var(--reai-card-2);
  border-radius: 8px;
}

.sub {
  margin: 12px 0 8px;
  font-size: var(--reai-fs-caption);
  font-weight: var(--reai-fw-semibold);
  line-height: var(--reai-lh-tight);
  color: var(--reai-text-soft);
}

.suggest {
  display: block;
  width: 100%;
  padding: 10px;
  margin-bottom: 8px;
  font-size: var(--reai-fs-caption);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-main);
  text-align: left;
  cursor: pointer;
  background: var(--reai-card);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
}

.suggest:hover {
  border-color: var(--reai-primary);
}

/* 原生 button 不继承 Element Plus 焦点环，显式给键盘焦点 */
.suggest:focus-visible {
  outline: 2px solid var(--reai-primary);
  outline-offset: 2px;
}

@media (width <= 1024px) {
  .side {
    flex: none;
    width: 100%;
  }
}
</style>
