<template>
  <div class="vision-card">
    <div v-for="(item, i) in cards" :key="`${item.category}-${i}`" class="vision-item">
      <span class="tag">{{ item.category }}</span>
      <span class="conf">置信 {{ item.confidence.toFixed(2) }}</span>
      <p class="desc">{{ item.desc }}</p>
      <p v-if="item.degraded" class="muted">规则降级结果，仅供参考</p>
      <p v-if="item.need_human" class="human">已转人工复核，请稍等</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// VLM 瑕疵检测卡（蓝框，对齐页面设计 §3.1/§3.2：类别/置信度/描述 + 低置信转人工，不硬答）
import { computed } from 'vue';
import type { VisionInspection } from '@/types/agent';

const props = defineProps<{ inspections: VisionInspection[] }>();

const cards = computed(() => (Array.isArray(props.inspections) ? props.inspections : []));
</script>

<style scoped>
.vision-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.vision-item {
  padding: 8px 10px;
  background: var(--reai-card);
  border: 1px solid var(--reai-accent);
  border-radius: 8px;
}

.tag {
  display: inline-block;
  padding: 2px 8px;
  margin-right: 8px;
  font-size: 12px;
  color: var(--reai-nav-active);
  background: var(--reai-bubble-user);
  border-radius: 10px;
}

.conf {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--reai-text-main);
}

.muted {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.human {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--reai-notice);
}
</style>
