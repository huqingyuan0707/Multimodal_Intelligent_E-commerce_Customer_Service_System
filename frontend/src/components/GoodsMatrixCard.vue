<!-- 颜色×尺码矩阵（服装必需：行=颜色，列=尺码，格子=售价+可售库存）
     对齐 页面设计.md §3.10 + design.pen「商品管理-/goods」画板。 -->
<template>
  <div class="matrix-card">
    <p class="matrix-title">颜色×尺码矩阵（服装必需）</p>
    <p class="matrix-hint">行 = 颜色，列 = 尺码，格子 = 售价 + 可售库存；点击上方 SPU 切换</p>
    <table v-if="selected && matrixRows.length" class="matrix">
      <thead>
        <tr>
          <th class="corner">颜色</th>
          <th v-for="z in matrixSizes" :key="z">{{ z }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in matrixRows" :key="r.color">
          <th>{{ r.color }}</th>
          <td v-for="c in r.cells" :key="c.size" :class="{ out: c.sku && c.sku.available <= 0 }">
            <template v-if="c.sku">
              <div class="cell-price">{{ formatCents(c.sku.sale_price) }}</div>
              <div class="cell-stock">
                {{ c.sku.available > 0 ? `可售 ${c.sku.available}` : '缺货' }}
              </div>
            </template>
            <span v-else class="cell-empty">—</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="matrix-hint">从上方表格点击 SPU 查看颜色×尺码矩阵</p>
  </div>
</template>

<script setup lang="ts">
// 颜色×尺码矩阵组件：行=颜色、列=尺码，格子=售价+可售库存
import { computed } from 'vue';
import { formatCents } from '@/types/shop';
import type { GoodsItem } from '@/types/shop';

const props = defineProps<{ selected: GoodsItem | null }>();

const matrixSizes = computed(() => [...new Set((props.selected?.skus ?? []).map(s => s.size))]);

const matrixRows = computed(() => {
  const skus = props.selected?.skus ?? [];
  const colors = [...new Set(skus.map(s => s.color))];
  return colors.map(color => ({
    color,
    cells: matrixSizes.value.map(size => ({
      size,
      sku: skus.find(s => s.color === color && s.size === size) ?? null,
    })),
  }));
});
</script>

<style scoped>
.matrix-card {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  background: var(--reai-card);
  box-shadow: var(--reai-shadow-card);
}

.matrix-title {
  margin: 0 0 4px;
  font-size: var(--reai-fs-title);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}

.matrix-hint {
  margin: 0 0 10px;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-soft);
}

.matrix {
  width: 100%;
  border-collapse: collapse;
}

.matrix th,
.matrix td {
  padding: 8px 10px;
  border: 1px solid var(--reai-border);
  text-align: center;
  font-size: var(--reai-fs-body-sm);
}

.matrix th {
  background: var(--reai-card-2);
  color: var(--reai-text-muted);
  font-weight: var(--reai-fw-medium);
}

.matrix .corner {
  width: 90px;
}

.cell-price {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}

.cell-stock {
  margin-top: 2px;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
}

.matrix td.out .cell-stock {
  color: var(--reai-notice);
  font-weight: var(--reai-fw-medium);
}

.cell-empty {
  color: var(--reai-text-soft);
}
</style>
