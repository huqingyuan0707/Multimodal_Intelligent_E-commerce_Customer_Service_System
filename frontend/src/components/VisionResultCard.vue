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
.vlm {
  padding: 8px;
  margin-top: 6px;
  background: var(--reai-card);
  border: 1px solid var(--reai-primary);
  border-radius: 8px;
}
.vlm-title {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.vlm-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: 13px;
}
</style>
