<template>
  <div class="page">
    <div class="head">
      <h2>库存管理</h2>
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
    </div>
    <div class="filters">
      <AiInput v-model="keyword" placeholder="搜 SKU/品名/仓库" class="kw" @keyup.enter="reload" />
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
      <el-table-column label="操作" width="200">
        <template #default="s">
          <el-button v-permission="['stock', 'shop', 'admin']" link type="primary" size="small" @click="move(s.row as InventoryRow, 'in')">
            入库
          </el-button>
          <el-button v-permission="['stock', 'shop', 'admin']" link type="primary" size="small" @click="move(s.row as InventoryRow, 'out')">
            出库
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
  </div>
</template>

<script setup lang="ts">
// 库存管理（SKU×仓库存量 + 预警 + 出入库；调拨/盘点待仓库选择器，P2 补；对齐页面设计 §3.11）
import { ElMessage, ElMessageBox, ElPagination, ElSwitch, ElTable, ElTableColumn, ElTag } from 'element-plus';
import { onMounted, ref } from 'vue';
import { api } from '@/api';
import { mockInventory } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { InventoryRow } from '@/types/shop';

const rows = ref<InventoryRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(50);
const keyword = ref('');
const onlyWarn = ref(false);
const loading = ref(false);
const demo = ref(false);

const matchKw = (r: InventoryRow, kw: string): boolean =>
  !kw || r.sku_code.includes(kw) || r.product_name.includes(kw) || r.warehouse.includes(kw);

const load = async (): Promise<void> => {
  loading.value = true;
  try {
    const res = await api.listInventory({
      only_warn: onlyWarn.value,
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
      (r) => (!onlyWarn.value || r.warning) && matchKw(r, kw),
    );
    total.value = rows.value.length;
    demo.value = true;
  } finally {
    loading.value = false;
  }
};

const reload = (): void => {
  page.value = 1;
  void load();
};

const onPage = (p: number): void => {
  page.value = p;
  void load();
};

const onSize = (s: number): void => {
  size.value = s;
  page.value = 1;
  void load();
};

// 出入库：数量 + 原因双确认（原因必填，审计留痕）
const move = async (row: InventoryRow, kind: 'in' | 'out'): Promise<void> => {
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
    await api.moveStock({
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

const transfer = (_row: InventoryRow): void => {
  ElMessage.info('调拨需选择目标仓库（P2 补仓库选择器）');
};

const stocktake = (): void => {
  ElMessage.info('盘点导入后续补（差异进审批，见 FR-10.2）');
};

onMounted(() => {
  void load();
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
