<template>
  <section v-if="rows.length" class="warn-card" aria-label="安全库存预警">
    <div class="warn-head">
      <span class="warn-title">缺货预警 {{ rows.length }} 个 SKU</span>
      <AiButton size="small" type="primary" :loading="loadingAll" @click="replenishAll">
        一键补货
      </AiButton>
    </div>
    <div v-for="r in rows" :key="r.id" class="warn-row">
      <span class="warn-sku">{{ r.sku_code }}</span>
      <span class="warn-name">{{ r.product_name }}</span>
      <div class="bar" aria-hidden="true">
        <div class="bar-fill" :style="{ width: `${barPct(r)}%` }" />
      </div>
      <span class="warn-val">可用 {{ r.available }} / 安全线 {{ r.warn_line }}</span>
      <AiButton
        size="small"
        link
        type="primary"
        :loading="loadingSku === r.sku_id"
        @click="replenishRow(r)"
      >
        补货
      </AiButton>
    </div>
    <p class="warn-note">预警行一键补货（→ 审批通过后入库）；缺货 SKU 联动客服话术「补货中」</p>
  </section>
</template>

<script setup lang="ts">
// 预警卡（低于安全线红条 + 一键补货进审批，对齐页面设计 §3.11 + 画板 StockWarnCard）
// 自拉 only_warn=true 全局预警（limit 100），不依赖父表格的分页数据；补货走 POST /inventory/replenish 恒进审批。
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { listInventoryApi, replenishApi } from '@/api';
import { mockInventory } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import type { InventoryRow } from '@/types/shop';

const rows = ref<InventoryRow[]>([]);
const loadingAll = ref(false);
const loadingSku = ref('');

const barPct = (r: InventoryRow) => {
  if (r.warn_line <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((r.available / r.warn_line) * 100));
};

const load = async () => {
  try {
    const res = await listInventoryApi({ only_warn: true, page: 1, size: 100 });
    rows.value = res.items as InventoryRow[];
  } catch {
    rows.value = mockInventory.filter(r => r.warning);
  }
};

// 单行补货：默认补到安全线（差异量），弹窗可改
const replenishRow = async (row: InventoryRow) => {
  const defaultQty = Math.max(1, row.warn_line - row.available);
  let qtyStr = '';
  try {
    ({ value: qtyStr } = await ElMessageBox.prompt(
      `为 ${row.sku_code} 补货（建议 ${defaultQty} 件）`,
      '补货',
      { inputValue: String(defaultQty) },
    ));
  } catch {
    return;
  }
  const qty = Number(qtyStr);
  if (!Number.isInteger(qty) || qty <= 0) {
    ElMessage.warning('请输入正整数数量');
    return;
  }
  loadingSku.value = row.sku_id;
  try {
    await replenishApi({ sku_id: row.sku_id, qty, reason: `低于安全线补货 ${row.sku_code}` });
    ElMessage.success(`补货需求已提交审批（${qty} 件）`);
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '补货提交失败');
  } finally {
    loadingSku.value = '';
  }
};

// 一键补货：按 SKU 去重（多仓只保 max 差值），逐条生成补货审批
const replenishAll = async () => {
  if (!rows.value.length) {
    return;
  }
  try {
    await ElMessageBox.confirm('为所有预警 SKU 各提交一条补货审批（默认补至安全线）？', '一键补货');
  } catch {
    return;
  }
  loadingAll.value = true;
  const skuMap = new Map<string, { sku_id: string; qty: number; name: string }>();
  for (const r of rows.value) {
    const need = Math.max(1, r.warn_line - r.available);
    const exist = skuMap.get(r.sku_id);
    if (!exist || need > exist.qty) {
      skuMap.set(r.sku_id, { sku_id: r.sku_id, qty: need, name: r.sku_code });
    }
  }
  let ok = 0;
  for (const item of skuMap.values()) {
    try {
      await replenishApi({ sku_id: item.sku_id, qty: item.qty, reason: `一键补货 ${item.name}` });
      ok += 1;
    } catch {
      // 单条失败不中断
    }
  }
  loadingAll.value = false;
  await load();
  ElMessage.success(`已提交 ${ok}/${skuMap.size} 条补货审批`);
};

const reload = () => load();

defineExpose({ reload });

onMounted(load);
</script>

<style scoped>
.warn-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--reai-notice-soft);
  border-radius: 12px;
}

.warn-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.warn-title {
  font-size: var(--reai-fs-body);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-notice);
}

.warn-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--reai-fs-body-sm);
}

.warn-sku {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
  min-width: 170px;
}

.warn-name {
  color: var(--reai-text-muted);
  min-width: 120px;
}

.bar {
  flex: 1;
  max-width: 180px;
  height: 6px;
  background: var(--reai-card-2);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--reai-notice);
  border-radius: 3px;
}

.warn-val {
  color: var(--reai-text-main);
  white-space: nowrap;
}

.warn-note {
  margin: 0;
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-muted);
}
</style>
