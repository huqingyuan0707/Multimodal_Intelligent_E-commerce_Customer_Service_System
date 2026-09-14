<template>
  <div v-for="v in inspections" :key="v.category" class="vlm">
    <p class="vlm-title">{{ v.category }} · 置信度 {{ pct(v.confidence) }}</p>
    <p class="vlm-row">
      {{ v.desc }}
      <el-tag size="small" type="info">AI 回复</el-tag>
    </p>
    <p class="vlm-row">{{ v.need_human ? '已转人工复核' : '建议：拍照留存后申请换货' }}</p>
  </div>
</template>

<script setup lang="ts">
// VLM 瑕疵检测蓝卡（类别/置信度/描述；<0.6 显示转人工复核不硬答，对齐画布 vlmCard）
import { ElTag } from 'element-plus';
import type { VisionInspection } from '@/types/agent';

defineProps<{ inspections: VisionInspection[] }>();

const pct = (v: number) => `${Math.round(v * 100)}%`;
</script>

<style scoped>
/* 浅泡内嵌蓝卡：浅底 + 深字（原 --reai-card 深底套浅泡，深字深底糊成截图红框；对齐画布 vlmCard #4F6BFF1F） */
.vlm {
  padding: 8px 10px;
  margin-top: 8px;
  font-size: var(--reai-fs-body-sm);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-on-light);
  background: var(--reai-primary-soft);
  border: 1px solid var(--reai-primary);
  border-radius: 8px;
}
.vlm-title {
  margin: 0 0 6px;
  font-size: var(--reai-fs-body-sm);
  font-weight: var(--reai-fw-semibold);
  line-height: var(--reai-lh-tight);
}
.vlm-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: var(--reai-fs-body-sm);
  line-height: var(--reai-lh-body);
}
</style>
