<template>
  <el-dialog
    :model-value="modelValue"
    title="新建采购单（草稿）"
    width="680px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="form">
      <span class="form-label">供应商（必选）</span>
      <el-select v-model="form.supplierId" filterable placeholder="选择供应商" class="fill">
        <el-option v-for="s in supplierOptions" :key="s.id" :label="s.name" :value="s.id" />
      </el-select>
      <span class="form-label">收货仓（质检入库前必须指定）</span>
      <el-select v-model="form.warehouseId" placeholder="未指定" class="fill">
        <el-option label="未指定" value="" />
        <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <span class="form-label">采购明细（行名由 SKU 快照回填，单价按元录入）</span>
      <div v-for="(line, i) in form.lines" :key="i" class="line">
        <el-select v-model="line.skuId" filterable placeholder="选择 SKU" class="line-sku">
          <el-option v-for="o in skuOptions" :key="o.id" :label="o.label" :value="o.id" />
        </el-select>
        <el-input-number v-model="line.qty" :min="1" :max="100000" :step="1" />
        <el-input-number v-model="line.priceYuan" :min="0" :precision="2" :step="1" />
        <AiButton link type="danger" @click="removeLine(i)">移除</AiButton>
      </div>
      <AiButton link type="primary" @click="addLine">+ 添加明细行</AiButton>
      <span class="form-label">预计到货日</span>
      <el-date-picker v-model="form.eta" type="date" value-format="YYYY-MM-DD" />
    </div>
    <template #footer>
      <AiButton @click="emit('update:modelValue', false)">取消</AiButton>
      <AiButton type="primary" :loading="submitting" @click="submit">创建草稿单</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 新建采购单弹窗（恒为草稿，审批前不动账；行名/SKU 快照由服务端回填，对齐页面设计 §3.12）
// 候选项全部来自真接口：供应商/仓库/SKU，失败置空并提示，不编造数据
import { ElDatePicker, ElInputNumber, ElMessage, ElOption, ElSelect } from 'element-plus';
import { ref, watch } from 'vue';
import { createPurchaseOrderApi, listGoodsApi, listSuppliersApi, listWarehousesApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { SupplierItem } from '@/types/shop';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits(['update:modelValue', 'done']);

const submitting = ref(false);
const supplierOptions = ref<SupplierItem[]>([]);
const warehouses = ref<{ id: string; name: string }[]>([]);
const skuOptions = ref<{ id: string; label: string }[]>([]);
const form = ref({
  supplierId: '',
  warehouseId: '',
  lines: [{ skuId: '', qty: 1, priceYuan: 0 }] as {
    skuId: string;
    qty: number;
    priceYuan: number;
  }[],
  eta: '',
});

// 打开时重置表单并拉候选（供应商/仓库拉一次复用，SKU 同理）
watch(
  () => props.modelValue,
  open => {
    if (!open) {
      return;
    }
    form.value = {
      supplierId: '',
      warehouseId: '',
      lines: [{ skuId: '', qty: 1, priceYuan: 0 }],
      eta: '',
    };
    loadCandidates();
  },
);

const loadCandidates = async () => {
  if (!supplierOptions.value.length) {
    try {
      const res = await listSuppliersApi({ page: 1, size: 100 });
      supplierOptions.value = res.items;
    } catch {
      supplierOptions.value = [];
      ElMessage.error('供应商候选加载失败，请刷新重试');
    }
  }
  if (!warehouses.value.length) {
    try {
      warehouses.value = await listWarehousesApi();
    } catch {
      warehouses.value = [];
      ElMessage.error('仓库列表加载失败，可先不指定收货仓');
    }
  }
  if (!skuOptions.value.length) {
    try {
      const goods = await listGoodsApi({ page: 1, size: 100 });
      skuOptions.value = goods.items.flatMap(
        (p: {
          name: string;
          skus: { id: string; sku_code: string; color: string; size: string }[];
        }) =>
          (p.skus ?? []).map(sku => ({
            id: sku.id,
            label: `${p.name}｜${sku.color || '-'} / ${sku.size || '-'}｜${sku.sku_code}`,
          })),
      );
    } catch {
      skuOptions.value = [];
      ElMessage.error('SKU 候选加载失败，请刷新重试');
    }
  }
};

const addLine = () => {
  form.value.lines.push({ skuId: '', qty: 1, priceYuan: 0 });
};

const removeLine = (index: number) => {
  form.value.lines.splice(index, 1);
};

const submit = async () => {
  if (!form.value.supplierId) {
    ElMessage.warning('请选择供应商');
    return;
  }
  const lines = form.value.lines
    .filter(line => line.skuId)
    .map(line => ({ sku_id: line.skuId, qty: line.qty, price: Math.round(line.priceYuan * 100) }));
  if (!lines.length) {
    ElMessage.warning('请至少选择一个 SKU');
    return;
  }
  if (lines.some(line => line.qty <= 0)) {
    ElMessage.warning('采购数量必须为正整数');
    return;
  }
  submitting.value = true;
  try {
    await createPurchaseOrderApi({
      supplier_id: form.value.supplierId,
      warehouse_id: form.value.warehouseId,
      items: lines,
      eta: form.value.eta ?? '',
    });
    ElMessage.success('采购单已创建（草稿）');
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

.fill {
  width: 100%;
}

.line {
  display: flex;
  gap: 8px;
  align-items: center;
}

.line-sku {
  flex: 1;
}
</style>
