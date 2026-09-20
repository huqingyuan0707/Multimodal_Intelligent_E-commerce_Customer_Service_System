<template>
  <el-dialog
    :model-value="modelValue"
    title="新建供应商"
    width="440px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="form">
      <span class="form-label">名称（必填）</span>
      <AiInput v-model="form.name" placeholder="供应商名称" />
      <span class="form-label">账期说明</span>
      <AiInput v-model="form.payTerms" placeholder="如：账期30天" />
      <span class="form-label">历史合格率（%）</span>
      <el-input-number v-model="form.passRate" :min="0" :max="100" :precision="1" />
    </div>
    <template #footer>
      <AiButton @click="emit('update:modelValue', false)">取消</AiButton>
      <AiButton type="primary" :loading="submitting" @click="submit">创建</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 新建供应商弹窗（名称必填，合格率以百分比录入换算 0~1 落库；对齐页面设计 §3.12）
import { ElInputNumber, ElMessage } from 'element-plus';
import { ref } from 'vue';
import { createSupplierApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

defineProps<{ modelValue: boolean }>();
const emit = defineEmits(['update:modelValue', 'done']);

const submitting = ref(false);
const form = ref({ name: '', payTerms: '', passRate: 100 });

const submit = async () => {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写供应商名称');
    return;
  }
  submitting.value = true;
  try {
    await createSupplierApi({
      name: form.value.name.trim(),
      pay_terms: form.value.payTerms.trim(),
      pass_rate: form.value.passRate / 100,
    });
    ElMessage.success('供应商已创建');
    emit('update:modelValue', false);
    emit('done');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
};
</script>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-label {
  font-size: 13px;
  color: var(--reai-text-muted);
}
</style>
