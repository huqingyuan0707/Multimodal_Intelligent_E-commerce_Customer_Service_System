<template>
  <div class="page">
    <div class="head">
      <h2>库存管理</h2>
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
    </div>
    <div class="filters">
      <AiInput v-model="keyword" placeholder="搜 SKU/品名/仓库" class="kw" @keyup.enter="reload" />
      <el-select v-model="warehouseId" placeholder="仓库" class="sel" @change="reload">
        <el-option label="全部仓库" value="" />
        <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <span class="warn-switch">只看预警</span>
      <el-switch v-model="onlyWarn" @change="reload" />
      <AiButton @click="reload">查询</AiButton>
      <AiButton @click="stocktake">盘点</AiButton>
    </div>
    <p class="formula">可用库存 = 在库 − 预占 − 锁定（超卖率必须为 0）</p>
    <el-table v-loading="loading" :data="rows" class="table">
      <el-table-column prop="sku_code" label="SKU" />
      <el-table-column prop="product_name" label="品名" />
      <el-table-column prop="warehouse" label="仓库" width="100" />
      <el-table-column prop="qty" label="在库" width="80" />
      <el-table-column prop="reserved" label="预占" width="80" />
      <el-table-column prop="locked" label="锁定" width="80" />
      <el-table-column label="可用" width="110">
        <template #default="s">
          {{ s.row.available }}
          <el-tag v-if="s.row.warning" type="warning" size="small">预警</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="warn_line" label="安全线" width="80" />
      <el-table-column label="操作" width="270">
        <template #default="s">
          <el-button v-permission="['stock', 'shop', 'admin']" link type="primary" size="small" @click="move(s.row as InventoryRow, 'in')">
            入库
          </el-button>
          <el-button v-permission="['stock', 'shop', 'admin']" link type="primary" size="small" @click="move(s.row as InventoryRow, 'out')">
            出库
          </el-button>
          <el-button link type="primary" size="small" @click="openMoves(s.row as InventoryRow)">
            流水
          </el-button>
          <el-button link type="primary" size="small" @click="transfer(s.row as InventoryRow)">
            调拨
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="onPage"
        @size-change="onSize"
      />
    </div>
    <el-drawer v-model="movesDrawer" :title="movesTitle" size="560px">
      <el-table v-loading="movesLoading" :data="moves" size="small">
        <el-table-column prop="kind_label" label="类型" width="90" />
        <el-table-column prop="delta" label="数量" width="80" />
        <el-table-column prop="reason" label="原因" />
        <el-table-column prop="actor" label="操作人" width="100" />
        <el-table-column prop="created_at" label="时间" width="160" />
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 库存管理（SKU×仓库存量 + 预警 + 出入库/调拨 + 流水抽屉；对齐页面设计 §3.11）
// 调拨走 prompt 三步确认（目标仓/数量/原因），仓库选择器 P2 再换成下拉组件
import { ElDrawer, ElMessage, ElMessageBox, ElOption, ElPagination, ElSelect, ElSwitch, ElTable, ElTableColumn, ElTag } from 'element-plus';
import { onMounted, ref } from 'vue';
import { listInventoryApi, listMovesApi, listWarehousesApi, moveStockApi } from '@/api';
import { mockInventory } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { InventoryRow, StockMoveItem } from '@/types/shop';

const rows = ref<InventoryRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(50);
const keyword = ref('');
const onlyWarn = ref(false);
const warehouses = ref<{ id: string; name: string }[]>([]);
const warehouseId = ref('');
const loading = ref(false);
const demo = ref(false);
const movesDrawer = ref(false);
const movesTitle = ref('出入库流水');
const movesLoading = ref(false);
const moves = ref<StockMoveItem[]>([]);

const matchKw = (r: InventoryRow, kw: string) =>
  !kw || r.sku_code.includes(kw) || r.product_name.includes(kw) || r.warehouse.includes(kw);

const load = async () => {
  loading.value = true;
  try {
    const res = await listInventoryApi({
      only_warn: onlyWarn.value,
      warehouse_id: warehouseId.value || undefined,
      page: page.value,
      size: size.value,
    });
    const kw = keyword.value.trim();
    rows.value = res.items.filter((r) => matchKw(r, kw));
    total.value = res.total;
    demo.value = false;
  } catch {
    const kw = keyword.value.trim();
    rows.value = mockInventory.filter(
      (r) =>
        (!onlyWarn.value || r.warning) &&
        (!warehouseId.value || r.warehouse_id === warehouseId.value) &&
        matchKw(r, kw),
    );
    total.value = rows.value.length;
    demo.value = true;
  } finally {
    loading.value = false;
  }
};

// 仓库下拉：真接口优先，失败从演示行里去重凑合（mock 行自带 warehouse_id/name）
const loadWarehouses = async () => {
  try {
    warehouses.value = await listWarehousesApi();
  } catch {
    const seen = new Map<string, string>();
    mockInventory.forEach((r) => {
      if (!seen.has(r.warehouse_id)) {
        seen.set(r.warehouse_id, r.warehouse);
      }
    });
    warehouses.value = [...seen.entries()].map(([id, name]) => ({ id, name }));
  }
};

// 出入库流水抽屉（按 SKU 倒序；后端暂无数据时如实报错，不伪造）
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

// 出入库：数量 + 原因双确认（原因必填，审计留痕）
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
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  }
};

const transfer = async (row: InventoryRow) => {
  const targets = warehouses.value.filter((w) => w.id !== row.warehouse_id);
  if (!targets.length) {
    ElMessage.warning('没有可调拨的目标仓库');
    return;
  }
  let targetId: string;
  try {
    ({ value: targetId } = await ElMessageBox.prompt(
      `从「${row.warehouse}」调往哪个仓库？（可选 ${targets.map((w) => `${w.name}=${w.id}`).join('、')}）`,
      '目标仓库',
      { inputValue: targets[0].id },
    ));
  } catch {
    return;
  }
  if (!targets.some((w) => w.id === targetId.trim())) {
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
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '调拨失败');
  }
};

const stocktake = () => {
  ElMessage.info('盘点导入后续补（差异进审批，见 FR-10.2）');
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

.head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--reai-text-main);
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
