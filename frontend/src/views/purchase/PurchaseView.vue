<template>
  <div class="page">
    <!-- 供应商（账期 + 合格率；对齐画板 pur-sup：服务端分页 默认20 可切10/20/50/100） -->
    <div class="card">
      <div class="filters">
        <AiInput
          v-model="supKeyword"
          placeholder="搜供应商名称"
          class="kw"
          @keyup.enter="reloadSuppliers"
        />
        <AiButton @click="reloadSuppliers">查询</AiButton>
        <AiButton
          v-permission="['shop', 'stock', 'admin']"
          type="primary"
          @click="supplierOpen = true"
        >
          新建供应商
        </AiButton>
      </div>
      <el-table v-loading="supLoading" :data="suppliers" class="table">
        <el-table-column prop="name" label="供应商" min-width="160" />
        <el-table-column prop="pay_terms" label="账期" min-width="120">
          <template #default="s">{{ s.row.pay_terms || '—' }}</template>
        </el-table-column>
        <el-table-column label="合格率" width="100">
          <template #default="s">{{ rateText(s.row.pass_rate) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
      </el-table>
      <div class="pager">
        <el-pagination
          :current-page="supPage"
          :page-size="supSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="supTotal"
          layout="sizes, prev, pager, next, total"
          @current-change="onSupPage"
          @size-change="onSupSize"
        />
      </div>
    </div>

    <!-- 采购单状态机（对齐画板 pur-flow：草稿→审批→到货→质检→入库，按钮按 allowed_actions 置灰） -->
    <div class="card">
      <div class="filters">
        <el-select v-model="status" placeholder="状态" class="sel" @change="reload">
          <el-option label="全部状态" value="" />
          <el-option
            v-for="(label, key) in STATUS_OPTIONS"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
        <AiButton @click="reload">查询</AiButton>
        <AiButton
          v-permission="['shop', 'stock', 'admin']"
          type="primary"
          @click="createOpen = true"
        >
          新建采购单
        </AiButton>
        <span class="hint"
          >审批统一走审批中心；审批前不动账；质检合格才入库，不合格退供（终态）</span
        >
      </div>
      <el-table v-loading="loading" :data="rows" class="table">
        <el-table-column prop="id" label="单号" min-width="150" />
        <el-table-column label="供应商" min-width="130">
          <template #default="s">{{ s.row.supplier_name || s.row.supplier_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="收货仓" width="110">
          <template #default="s">{{ s.row.warehouse_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="明细" min-width="200">
          <template #default="s">
            <span class="lines">{{ linesText(s.row.items) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="qty_total" label="件数" width="70" />
        <el-table-column label="金额" width="100">
          <template #default="s">{{ formatCents(s.row.amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="s">
            <el-tag :type="purchaseTagOf(s.row.status)">{{ s.row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预计到货" width="110">
          <template #default="s">{{ s.row.eta || '未定' }}</template>
        </el-table-column>
        <el-table-column label="质检" width="110">
          <template #default="s">
            <el-tag v-if="s.row.qc_result === 'pass'" type="success" size="small">合格</el-tag>
            <el-tag v-else-if="s.row.qc_result === 'fail'" type="danger" size="small">退供</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="230">
          <template #default="s">
            <!-- 草稿单无本地审批：建单即落审批中心，这里只做跳转引导 -->
            <AiButton
              v-if="s.row.status === 'draft'"
              v-permission="['shop', 'stock', 'admin']"
              link
              type="primary"
              size="small"
              @click="goApproval(s.row as PurchaseOrderItem)"
            >
              审批中 · 去审批中心
            </AiButton>
            <AiButton
              v-permission="['shop', 'stock', 'admin']"
              link
              type="primary"
              size="small"
              :disabled="!s.row.allowed_actions.includes('receive')"
              @click="receive(s.row as PurchaseOrderItem)"
            >
              到货登记
            </AiButton>
            <AiButton
              v-permission="['shop', 'stock', 'admin']"
              link
              type="warning"
              size="small"
              :disabled="!s.row.allowed_actions.includes('qc')"
              @click="qc(s.row as PurchaseOrderItem)"
            >
              质检
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
    </div>

    <SupplierForm v-model="supplierOpen" @done="loadSuppliers" />
    <PurchaseCreateForm v-model="createOpen" @done="load" />
  </div>
</template>

<script setup lang="ts">
// 采购协同：供应商列表 + 采购单状态机（草稿→审批→到货→质检→入库）+ 到货质检
// 对齐页面设计 §3.12 / 画板 采购协同-/purchase；金额一律分；建单表单拆 PurchaseCreateForm/SupplierForm
import {
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { listPurchaseOrdersApi, listSuppliersApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { PurchaseOrderItem, SupplierItem } from '@/types/shop';
import { formatCents, purchaseTagOf } from '@/types/shop';
import { usePurchaseOps } from '@/composables/usePurchaseOps';
import PurchaseCreateForm from './PurchaseCreateForm.vue';
import SupplierForm from './SupplierForm.vue';

// 状态筛选枚举（中文口径与后端 STATUS_LABELS 一致，行内展示走后端 status_label）
const STATUS_OPTIONS = {
  draft: '草稿',
  approved: '已审批',
  rejected: '已驳回',
  received: '已到货',
  stocked: '已入库',
  returned: '已退供',
} as const;

const suppliers = ref<SupplierItem[]>([]);
const supTotal = ref(0);
const supPage = ref(1);
const supSize = ref(20);
const supKeyword = ref('');
const supLoading = ref(false);
const supplierOpen = ref(false);

const rows = ref<PurchaseOrderItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const status = ref('');
const loading = ref(false);
const createOpen = ref(false);

const rateText = (rate: number) => `${(rate * 100).toFixed(1)}%`;

// 明细行摘要：最多展示两行，超出省略（防长列表撑爆单元格）
const linesText = (items: { name: string; qty: number }[]) =>
  (items ?? [])
    .slice(0, 2)
    .map(it => `${it.name || '未知商品'} ×${it.qty}`)
    .join('；') + ((items?.length ?? 0) > 2 ? ' …' : '');

const loadSuppliers = async () => {
  supLoading.value = true;
  try {
    const res = await listSuppliersApi({
      keyword: supKeyword.value.trim(),
      page: supPage.value,
      size: supSize.value,
    });
    suppliers.value = res.items;
    supTotal.value = res.total;
  } catch (e) {
    suppliers.value = [];
    supTotal.value = 0;
    ElMessage.error(e instanceof Error ? `加载供应商失败：${e.message}` : '加载供应商失败');
  } finally {
    supLoading.value = false;
  }
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listPurchaseOrdersApi({
      status: status.value,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载采购单失败：${e.message}` : '加载采购单失败');
  } finally {
    loading.value = false;
  }
};

const { receive, qc } = usePurchaseOps(load);

// 草稿单跳审批中心：按采购单号预填关键字，直达对应审批单
const router = useRouter();
const goApproval = (row: PurchaseOrderItem) => {
  router.push({ path: '/approvals', query: { keyword: row.id } });
};

const reloadSuppliers = () => {
  supPage.value = 1;
  loadSuppliers();
};

const onSupPage = (p: number) => {
  supPage.value = p;
  loadSuppliers();
};

const onSupSize = (s: number) => {
  supSize.value = s;
  supPage.value = 1;
  loadSuppliers();
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

onMounted(() => {
  loadSuppliers();
  load();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.card {
  background: var(--reai-bg-container);
  border-radius: 12px;
  padding: 16px;
}

.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.kw {
  width: 220px;
}

.sel {
  width: 130px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.table {
  width: 100%;
}

.lines {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
