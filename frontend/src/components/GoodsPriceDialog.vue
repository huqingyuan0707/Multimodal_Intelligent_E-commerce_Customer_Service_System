<!-- 改价弹窗 PriceForm：当前售价 → 新售价（元）+ 改价原因（必填）→ 提交审批
     改价恒进审批（红线，对齐 页面设计.md §3.10 + design.pen「商品管理-/goods」画板）。 -->
<template>
  <el-dialog v-model="visible" title="改价（将进入审批）" width="440px">
    <div class="price-form">
      <div class="price-row">
        <span class="price-label">当前售价</span>
        <span class="price-now">{{ formatCents(sku?.sale_price ?? 0) }}</span>
      </div>
      <div class="price-row">
        <span class="price-label">新售价（元）</span>
        <AiInput v-model="priceInput" placeholder="新售价（元）" class="price-input" />
      </div>
      <div class="price-row">
        <span class="price-label">改价原因</span>
        <AiInput v-model="reasonInput" placeholder="必填：审批人需要看到原因" class="price-input" />
      </div>
    </div>
    <template #footer>
      <AiButton @click="visible = false">取消</AiButton>
      <AiButton type="primary" class="price-submit" :loading="submitting" @click="submit">
        提交审批
      </AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 改价弹窗：金额校验 + 原因必填 + 提交审批（通过后才生效，账不动）
import { ElDialog, ElMessage } from 'element-plus';
import { ref, watch } from 'vue';
import { submitPriceChangeApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { formatCents } from '@/types/shop';
import type { SkuItem } from '@/types/shop';

const props = defineProps<{ modelValue: boolean; sku: SkuItem | null }>();
// 红线：defineEmits 用运行时数组形式（类型式声明强制 `: void`，与 no-restricted-syntax 冲突）
const emit = defineEmits(['update:modelValue']);

const visible = ref(props.modelValue);
watch(
  () => props.modelValue,
  open => {
    visible.value = open;
    if (open && props.sku) {
      priceInput.value = (props.sku.sale_price / 100).toFixed(2);
      reasonInput.value = '';
    }
  },
);
watch(visible, open => emit('update:modelValue', open));

const priceInput = ref('');
const reasonInput = ref('');
const submitting = ref(false);

const submit = async () => {
  const yuan = Number(priceInput.value);
  if (!Number.isFinite(yuan) || yuan <= 0) {
    ElMessage.warning('请输入大于 0 的金额');
    return;
  }
  if (!reasonInput.value.trim()) {
    ElMessage.warning('请填写改价原因（审批需要）');
    return;
  }
  if (!props.sku) return;
  submitting.value = true;
  try {
    await submitPriceChangeApi({
      skuId: props.sku.id,
      newPrice: Math.round(yuan * 100),
      reason: reasonInput.value.trim(),
    });
    ElMessage.success('改价已提交审批，通过后自动生效');
    visible.value = false;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败');
  } finally {
    submitting.value = false;
  }
};
</script>

<style scoped>
.price-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.price-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.price-label {
  width: 90px;
  flex-shrink: 0;
  font-size: var(--reai-fs-body-sm);
  color: var(--reai-text-muted);
}

.price-now {
  font-size: var(--reai-fs-body);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}

.price-input {
  flex: 1;
}

.price-submit {
  margin-left: 10px;
}
</style>
