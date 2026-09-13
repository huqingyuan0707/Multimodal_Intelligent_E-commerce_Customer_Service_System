<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="code" placeholder="租户编码" class="kw" />
      <AiInput v-model="tokens" placeholder="Token 总量" class="kw" />
      <AiInput v-model="concurrency" placeholder="并发上限" class="kw" />
      <AiButton v-permission="['admin']" type="primary" @click="submit">保存配额</AiButton>
    </div>
    <p class="hint">危险操作：保存前需二次确认，并记 tenant.quota 审计。</p>
  </div>
</template>

<script setup lang="ts">
// 配额表单：选中租户回填编码与配额，保存需双重 confirm（资损红线同级）
// 父组件经 setTenant 回填；props 仅作初始值，避免受控与非受控混用
import { ElMessage, ElMessageBox } from 'element-plus';
import { ref } from 'vue';
import { updateQuotaApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const props = defineProps<{ initialCode?: string }>();

const code = ref(props.initialCode ?? '');
const tokens = ref('');
const concurrency = ref('');

const setTenant = (c: string, t: number, cc: number) => {
  code.value = c;
  tokens.value = String(t);
  concurrency.value = String(cc);
};

const submit = async () => {
  if (!code.value.trim() || !Number(tokens.value) || !Number(concurrency.value)) {
    ElMessage.warning('请填写租户编码与正数配额');
    return;
  }
  await ElMessageBox.confirm(`确认修改租户「${code.value}」的配额吗？`, '危险操作');
  await ElMessageBox.confirm('配额变更即时生效，请再次确认', '二次确认');
  try {
    await updateQuotaApi({
      code: code.value.trim(),
      quota_tokens: Number(tokens.value),
      quota_concurrency: Number(concurrency.value),
    });
    ElMessage.success('配额已更新');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  }
};

defineExpose({ setTenant });
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.kw {
  width: 220px;
}

.hint {
  color: var(--reai-text-muted);
  font-size: 12px;
}
</style>
