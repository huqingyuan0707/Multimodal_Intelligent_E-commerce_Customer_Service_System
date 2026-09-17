<template>
  <el-drawer
    :model-value="modelValue"
    title="盘点导入"
    size="640px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="stocktake">
      <p class="tip">
        逐行填写实盘数量，账实不一致的行将自动进入审批（批准后才改账）；上传 .xlsx/.csv 解析为 P2。
      </p>

      <div class="line-head">
        <span>仓库</span>
        <span>SKU</span>
        <span>账面</span>
        <span>实盘</span>
        <span>差异</span>
        <span class="op"></span>
      </div>

      <div v-for="(line, idx) in lines" :key="line.key" class="line">
        <el-select
          v-model="line.warehouse_id"
          placeholder="仓库"
          filterable
          size="small"
          class="wh"
        >
          <el-option
            v-for="w in warehousesFor(line.sku_id)"
            :key="w.id"
            :label="w.name"
            :value="w.id"
          />
        </el-select>
        <el-select
          v-model="line.sku_id"
          placeholder="SKU"
          filterable
          size="small"
          class="sku"
          @change="onSkuChange(line)"
        >
          <el-option
            v-for="o in skuOptions"
            :key="o.sku_id"
            :label="`${o.sku_code}｜${o.product_name}`"
            :value="o.sku_id"
          />
        </el-select>
        <span class="book">{{ line.book_qty }}</span>
        <el-input
          v-model.number="line.counted"
          type="number"
          min="0"
          step="1"
          placeholder="实盘"
          size="small"
          class="counted"
        />
        <span class="diff" :class="diffClass(line)">{{ diffOf(line) }}</span>
        <AiButton link size="small" type="danger" @click="removeLine(idx)">删</AiButton>
      </div>

      <AiButton class="add" size="small" @click="addLine">+ 添加盘点行</AiButton>

      <AiInput v-model="reason" placeholder="盘点原因（必填 · 审计留痕）" />

      <div class="foot">
        <AiButton @click="emit('update:modelValue', false)">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">提交盘点</AiButton>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
// 盘点导入抽屉（差异进审批，对齐页面设计 §3.11 + 画板 iv_take）
// 链路：StocktakeDrawer → stocktakeApi → inventory_service.stocktake →（差异行进审批，账实一致免审）。
// 上传解析（.xlsx/.csv 拖入）为 P2，本期提供手动逐行录入；差异行红色突出，提交后展示结果。
import { ElMessage } from 'element-plus';
import { ref, watch } from 'vue';
import { listInventoryApi, stocktakeApi } from '@/api';
import { mockInventory } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { InventoryRow } from '@/types/shop';

type StocktakeLine = {
  key: string;
  warehouse_id: string;
  sku_id: string;
  book_qty: number;
  counted: number | undefined;
};

const props = defineProps<{
  modelValue: boolean;
  warehouses: { id: string; name: string }[];
}>();
const emit = defineEmits(['update:modelValue', 'done']);

const lines = ref<StocktakeLine[]>([]);
const reason = ref('');
const submitting = ref(false);
// SKU 候选：打开时拉全量库存（size 200），失败回 mock，保证「挑选的 SKU×仓库」一定真实存在
const skuRows = ref<InventoryRow[]>([]);
const skuOptions = ref<InventoryRow[]>([]);

const diffOf = (line: StocktakeLine) => {
  if (line.counted === undefined || line.counted === null || String(line.counted) === '') {
    return '—';
  }
  return (line.counted as number) - line.book_qty;
};

const diffClass = (line: StocktakeLine) => {
  const diff = diffOf(line);
  return diff === '—' ? '' : diff === 0 ? 'same' : 'diff-changed';
};

// 仓库候选与已选 SKU 联动：只给该 SKU 真实存在的仓库（后端 404 兜底，前端先挡一层）
const warehousesFor = (skuId: string) => {
  if (!skuId) {
    return props.warehouses;
  }
  return props.warehouses.filter(w =>
    skuRows.value.some(r => r.sku_id === skuId && r.warehouse_id === w.id),
  );
};

const onSkuChange = (line: StocktakeLine) => {
  line.warehouse_id = '';
  line.book_qty = 0;
  if (!line.sku_id) {
    return;
  }
  const candidates = warehousesFor(line.sku_id);
  // 默认选第一个有货仓，并带出账面数量
  if (candidates.length) {
    line.warehouse_id = candidates[0].id;
  }
  const row = skuRows.value.find(
    r => r.sku_id === line.sku_id && r.warehouse_id === line.warehouse_id,
  );
  line.book_qty = row?.qty ?? 0;
};

const addLine = () => {
  lines.value.push({
    key: `l-${Date.now()}-${lines.value.length}`,
    warehouse_id: '',
    sku_id: '',
    book_qty: 0,
    counted: undefined,
  });
};

const removeLine = (idx: number) => {
  lines.value.splice(idx, 1);
};

const loadCandidates = async () => {
  try {
    const res = await listInventoryApi({ page: 1, size: 200 });
    skuRows.value = res.items;
  } catch {
    skuRows.value = mockInventory;
  }
  const seen = new Map<string, InventoryRow>();
  skuRows.value.forEach(r => {
    if (!seen.has(r.sku_id)) {
      seen.set(r.sku_id, r);
    }
  });
  skuOptions.value = [...seen.values()];
};

const submit = async () => {
  const valid = lines.value.filter(Boolean).map(line => ({
    warehouse_id: line.warehouse_id,
    sku_id: line.sku_id,
    counted: line.counted,
  }));
  // 只提交填写完整的行：仓库 + SKU + 实盘均为非空
  const ready = valid.filter(
    l =>
      l.warehouse_id &&
      l.sku_id &&
      l.counted !== undefined &&
      String(l.counted) !== '' &&
      l.counted >= 0,
  );
  if (!ready.length) {
    ElMessage.warning('请至少填写一行完整的盘点明细（仓库 + SKU + 实盘数量）');
    return;
  }
  const text = reason.value.trim();
  if (!text) {
    ElMessage.warning('请填写盘点原因（审计留痕）');
    return;
  }
  submitting.value = true;
  try {
    const res = await stocktakeApi({
      lines: ready.map(l => ({
        warehouse_id: l.warehouse_id,
        sku_id: l.sku_id,
        counted: l.counted as number,
      })),
      reason: text,
    });
    const msg =
      res.diff_count > 0
        ? `盘点 ${res.checked} 行，${res.diff_count} 行有差异，已提交审批（批准后改账）`
        : `盘点 ${res.checked} 行，账实一致`;
    ElMessage.success(msg);
    emit('update:modelValue', false);
    emit('done');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '盘点提交失败');
  } finally {
    submitting.value = false;
  }
};

watch(
  () => props.modelValue,
  open => {
    if (open) {
      if (!lines.value.length) {
        addLine();
      }
      reason.value = '';
      loadCandidates();
    }
  },
);
</script>

<style scoped>
.stocktake {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tip {
  margin: 0;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
}

.line-head,
.line {
  display: grid;
  grid-template-columns: 1fr 1.4fr 60px 80px 56px 24px;
  gap: 8px;
  align-items: center;
}

.line-head {
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
}

.book,
.diff {
  font-size: var(--reai-fs-body-sm);
  color: var(--reai-text-main);
  text-align: right;
}

.diff.same {
  color: var(--reai-online);
}

.diff.diff-changed {
  color: var(--reai-notice);
  font-weight: var(--reai-fw-semibold);
}

.op {
  width: 24px;
}

.add {
  align-self: flex-start;
}

.foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
