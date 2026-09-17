<template>
  <div class="page">
    <!-- 预警卡（自拉 only_warn=true；出入库/盘点/补货后 reload） -->
    <StockWarnCard ref="warnRef" />

    <div class="filters">
      <AiInput
        v-model="keyword"
        placeholder="搜 SKU / 品名 / 仓库"
        class="kw"
        @keyup.enter="reload"
      />
      <el-select v-model="warehouseId" placeholder="仓库" class="sel" @change="reload">
        <el-option label="全部仓库" value="" />
        <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <span class="warn-switch">只看预警</span>
      <el-switch v-model="onlyWarn" @change="reload" />
      <AiButton @click="reload">查询</AiButton>
      <AiButton @click="stocktakeOpen = true">盘点</AiButton>
    </div>
    <p class="formula">可用库存 = 在库 − 预占 − 锁定（超卖率必须为 0）</p>
    <el-table v-loading="loading" :data="rows" class="table" :row-class-name="warnClass">
      <el-table-column prop="sku_code" label="SKU" min-width="160" />
      <el-table-column prop="product_name" label="品名" min-width="160" />
      <el-table-column prop="warehouse" label="仓库" width="100" />
      <el-table-column prop="qty" label="在库" width="80" />
      <el-table-column prop="reserved" label="预占" width="80" />
      <el-table-column prop="locked" label="锁定" width="80" />
      <el-table-column label="可用" width="130">
        <template #default="s">
          <span
            :style="{
              fontWeight: '600',
              color: s.row.warning ? 'var(--reai-notice)' : 'var(--reai-text-main)',
            }"
          >
            {{ s.row.available }}
          </span>
          <el-tag v-if="s.row.warning" type="warning" size="small">预警</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="warn_line" label="安全线" width="80" />
      <el-table-column label="操作" width="270">
        <template #default="s">
          <AiButton
            v-permission="['stock', 'shop', 'admin']"
            link
            type="primary"
            size="small"
            @click="move(s.row as InventoryRow, 'in')"
          >
            入库
          </AiButton>
          <AiButton
            v-permission="['stock', 'shop', 'admin']"
            link
            type="primary"
            size="small"
            @click="move(s.row as InventoryRow, 'out')"
          >
            出库
          </AiButton>
          <AiButton link type="primary" size="small" @click="openMoves(s.row as InventoryRow)">
            流水
          </AiButton>
          <AiButton link type="primary" size="small" @click="transfer(s.row as InventoryRow)">
            调拨
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next, total"
        @current-change="onPage"
        @size-change="onSize"
      />
    </div>

    <!-- 流水抽屉 -->
    <el-drawer v-model="movesDrawer" :title="movesTitle" size="560px">
      <el-table v-loading="movesLoading" :data="moves" size="small">
        <el-table-column prop="kind_label" label="类型" width="90" />
        <el-table-column prop="delta" label="数量" width="80" />
        <el-table-column prop="reason" label="原因" />
        <el-table-column prop="actor" label="操作人" width="100" />
        <el-table-column prop="created_at" label="时间" width="160" />
      </el-table>
    </el-drawer>

    <!-- 盘点抽屉（差异进审批，替换原占位） -->
    <StocktakeDrawer v-model="stocktakeOpen" :warehouses="warehouses" @done="onStocktakeDone" />
  </div>
</template>

<script setup lang="ts">
// 库存管理（SKU×仓库存量 + 预警卡 + 盘点导入 + 出入库/调拨 + 流水抽屉；对齐页面设计 §3.11）
// keyword 走服务端分页前过滤（GET /inventory?keyword=），前端不再做 client-side 过滤，修复分页语义不一致。
import {
  ElDrawer,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElPagination,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import { listInventoryApi, listMovesApi, listWarehousesApi, moveStockApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import StockWarnCard from './StockWarnCard.vue';
import StocktakeDrawer from './StocktakeDrawer.vue';
import type { InventoryRow, StockMoveItem } from '@/types/shop';

const warnRef = ref();
const rows = ref<InventoryRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const onlyWarn = ref(false);
const warehouses = ref<{ id: string; name: string }[]>([]);
const warehouseId = ref('');
const loading = ref(false);
const movesDrawer = ref(false);
const movesTitle = ref('出入库流水');
const movesLoading = ref(false);
const moves = ref<StockMoveItem[]>([]);
const stocktakeOpen = ref(false);

// 预警行整行橙底，画板 iv_r2/iv_r3 规格
const warnClass = ({ row }: { row: InventoryRow }) => (row.warning ? 'warn-row-bg' : '');

const load = async () => {
  loading.value = true;
  try {
    const res = await listInventoryApi({
      keyword: keyword.value.trim() || undefined,
      only_warn: onlyWarn.value,
      warehouse_id: warehouseId.value || undefined,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载库存失败：${e.message}` : '加载库存失败');
  } finally {
    loading.value = false;
  }
};

// 仓库下拉：真接口优先，失败置空并提示
const loadWarehouses = async () => {
  try {
    warehouses.value = await listWarehousesApi();
  } catch (e) {
    warehouses.value = [];
    ElMessage.error(e instanceof Error ? `加载仓库失败：${e.message}` : '加载仓库失败');
  }
};

// 出入库流水抽屉
const openMoves = async (row: InventoryRow) => {
  movesTitle.value = `${row.sku_code} 出入库流水`;
  movesDrawer.value = true;
  movesLoading.value = true;
  try {
    moves.value = await listMovesApi({ skuId: row.sku_id });
  } catch (e) {
    moves.value = [];
    ElMessage.error(e instanceof Error ? e.message : '流水加载失败');
  } finally {
    movesLoading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
};

const onPage = (p: number) => {
  page.value = p;
  load();
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  load();
};

// 盘点完成后：刷新表格 + 预警卡
const onStocktakeDone = () => {
  load();
  warnRef.value?.reload();
};

// 出入库：数量 + 原因双确认
const move = async (row: InventoryRow, kind: 'in' | 'out') => {
  const label = kind === 'in' ? '入库' : '出库';
  let qtyRaw: string;
  try {
    ({ value: qtyRaw } = await ElMessageBox.prompt(
      `${row.sku_code}｜${row.warehouse}，请输入${label}数量`,
      `${label}数量`,
    ));
  } catch {
    return;
  }
  const delta = Number(qtyRaw);
  if (!Number.isInteger(delta) || delta <= 0) {
    ElMessage.warning('请输入正整数数量');
    return;
  }
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt('请输入原因（审计留痕）', `${label}原因`));
  } catch {
    return;
  }
  try {
    await moveStockApi({
      kind,
      warehouse_id: row.warehouse_id,
      sku_id: row.sku_id,
      delta,
      reason: reason.trim() || '工作台操作',
    });
    ElMessage.success(`${label}成功`);
    load();
    warnRef.value?.reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  }
};

// 调拨：目标仓选择 → 数量 → 原因，三步 prompt
const transfer = async (row: InventoryRow) => {
  const targets = warehouses.value.filter(w => w.id !== row.warehouse_id);
  if (!targets.length) {
    ElMessage.warning('没有可调拨的目标仓库');
    return;
  }
  let targetId: string;
  try {
    ({ value: targetId } = await ElMessageBox.prompt(
      `从「${row.warehouse}」调往哪个仓库？（可选 ${targets.map(w => `${w.name}=${w.id}`).join('、')}）`,
      '目标仓库',
      { inputValue: targets[0].id },
    ));
  } catch {
    return;
  }
  if (!targets.some(w => w.id === targetId.trim())) {
    ElMessage.warning('目标仓库不存在，请从列表中选择');
    return;
  }
  let qtyRaw: string;
  try {
    ({ value: qtyRaw } = await ElMessageBox.prompt(
      `${row.sku_code} 可用 ${row.available}，请输入调拨数量`,
      '调拨数量',
    ));
  } catch {
    return;
  }
  const delta = Number(qtyRaw);
  if (!Number.isInteger(delta) || delta <= 0) {
    ElMessage.warning('请输入正整数数量');
    return;
  }
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt('请输入原因（审计留痕）', '调拨原因'));
  } catch {
    return;
  }
  try {
    await moveStockApi({
      kind: 'move',
      warehouse_id: row.warehouse_id,
      to_warehouse_id: targetId.trim(),
      sku_id: row.sku_id,
      delta,
      reason: reason.trim() || '工作台调拨',
    });
    ElMessage.success('调拨成功，已拆两行流水');
    load();
    warnRef.value?.reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '调拨失败');
  }
};

onMounted(() => {
  loadWarehouses();
  load();
});
</script>

<style scoped>
.page {
  padding: 16px;
}

.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 12px 0;
}

.kw {
  width: 240px;
}

.sel {
  width: 140px;
}

.warn-switch {
  font-size: 13px;
  color: var(--reai-text-muted);
}

.formula {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.table {
  width: 100%;
}

/* 预警行整行橙底（画板 iv_r2/iv_r3 规格），行级类名需 :deep 穿透 el-table 内部渲染 */
.table :deep(.warn-row-bg) {
  background: var(--reai-notice-soft);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
