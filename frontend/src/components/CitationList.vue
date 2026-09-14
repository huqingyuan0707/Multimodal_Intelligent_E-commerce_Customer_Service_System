<template>
  <div v-if="refs.length" class="cites">
    <p v-for="(c, i) in refs" :key="c.source" class="cite" @click="open(c.source)">
      [{{ i + 1 }}] {{ c.title }}
    </p>
    <button v-if="traceId" class="trace" @click="copy">trace_id：{{ traceId }}（复制）</button>
  </div>
</template>

<script setup lang="ts">
// 引用来源金卡（RAG 引用必现，可点跳原文；trace 一键复制，对齐画布 botCitation）
import { ElMessage } from 'element-plus';
import type { Reference } from '@/types/agent';

const props = defineProps<{ refs: Reference[]; traceId?: string }>();
const emit = defineEmits(['open']);

const open = (source: string) => {
  emit('open', source);
};

const copy = async () => {
  try {
    await navigator.clipboard.writeText(props.traceId ?? '');
    ElMessage.success('trace_id 已复制');
  } catch {
    ElMessage.info(`trace_id：${props.traceId ?? ''}`);
  }
};
</script>

<style scoped>
/* 浅泡内嵌金卡：浅底 + 深字（原 --reai-card 深底套浅泡，accent 青字在浅底上发虚；对齐画布 botCitation #E8A33D1F + 深字） */
.cites {
  padding: 8px 10px;
  margin-top: 8px;
  color: var(--reai-text-on-light);
  background: var(--reai-gold-soft);
  border: 1px solid var(--reai-gold);
  border-radius: 8px;
}
.cite {
  margin: 4px 0;
  font-size: var(--reai-fs-caption);
  font-weight: var(--reai-fw-medium);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-on-light-muted);
  cursor: pointer;
}
.trace {
  padding: 0;
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-micro);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-on-light-faint);
  cursor: pointer;
  background: none;
  border: none;
  word-break: break-all;
}
</style>
