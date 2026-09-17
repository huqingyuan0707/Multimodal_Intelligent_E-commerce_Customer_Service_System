<template>
  <div class="card">
    <h3 class="card-title">质检评分</h3>
    <el-empty v-if="loading" description="评分加载中…" :image-size="48" />
    <template v-else-if="score && score.score > 0">
      <p class="kv">
        综合分：<span class="big" :class="score.pass ? 'ok' : 'warn'">{{ score.score }}</span>
        <span class="muted">/ 5</span>
        <el-tag size="small" :type="score.pass ? 'success' : 'danger'" effect="plain">
          {{ score.pass ? '质检通过' : '未达标' }}
        </el-tag>
      </p>
      <p class="kv">
        问题解决：<span :class="score.resolution_ok ? 'ok' : 'warn'">{{
          score.resolution_ok ? '已解决' : '未解决'
        }}</span>
        <el-tag size="small" type="info" effect="plain">{{ sourceLabel }}</el-tag>
        <span v-if="score.reviewer" class="muted">复核人 {{ score.reviewer }}</span>
      </p>
      <p v-if="reason" class="reason">{{ reason }}</p>
      <p class="sub">人工改评（覆盖自动评分）</p>
      <div class="form">
        <el-rate v-model="formScore" />
        <el-switch v-model="formOk" active-text="问题已解决" />
        <el-input
          v-model="formComment"
          type="textarea"
          :rows="2"
          maxlength="200"
          placeholder="改评依据（可选）"
        />
        <AiButton size="small" type="primary" :loading="saving" @click="submit">提交改评</AiButton>
      </div>
    </template>
    <el-empty
      v-else
      description="会话解决后自动评分（AI 评审，模型不可用走规则兜底）"
      :image-size="48"
    />
  </div>
</template>

<script setup lang="ts">
// 质检评分卡（C 步收官）：resolved 会话展示自动评分 + 人工改评入口
// 对齐画布 workbench 面板质检卡与页面设计 §3.2；来源标签枚举走映射表
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AiButton from '@/shared/components/AiButton.vue';
import type { WorkbenchScore } from '@/api';

const props = defineProps<{
  score: WorkbenchScore | null;
  loading: boolean;
  saving: boolean;
}>();

const emit = defineEmits(['save']);

// 来源中文化：judge=AI 评审 / rule=规则兜底 / manual=人工复核
const SOURCE_LABEL = {
  judge: 'AI 评审',
  rule: '规则兜底',
  manual: '人工复核',
} as const;

const sourceLabel = computed(() => {
  const key = props.score?.source ?? '';
  return key in SOURCE_LABEL ? SOURCE_LABEL[key as keyof typeof SOURCE_LABEL] : key || '未评';
});

const reason = computed(() => String(props.score?.detail?.reason ?? '').trim());

// 改评表单：评分变化时回填当前值，避免上一会话草稿串场
const formScore = ref(0);
const formOk = ref(true);
const formComment = ref('');
watch(
  () => props.score,
  value => {
    formScore.value = value?.score && value.score > 0 ? value.score : 0;
    formOk.value = value?.resolution_ok ?? true;
    formComment.value = '';
  },
  { immediate: true },
);

const submit = () => {
  if (!formScore.value) {
    ElMessage.warning('请先打分（1-5 星）');
    return;
  }
  emit('save', {
    score: formScore.value,
    resolution_ok: formOk.value,
    comment: formComment.value.trim(),
  });
};
</script>

<style scoped>
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
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.big {
  font-size: var(--reai-fs-title);
  font-weight: var(--reai-fw-semibold);
}

.ok {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-online);
}

.warn {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-notice);
}

.muted {
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-muted);
}

.reason {
  margin: 8px 0;
  padding: 10px;
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

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}

.form :deep(.el-textarea),
.form :deep(.el-textarea__inner) {
  width: 100%;
}
</style>
