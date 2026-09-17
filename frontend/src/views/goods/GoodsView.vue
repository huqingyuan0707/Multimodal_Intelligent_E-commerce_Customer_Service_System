<!-- 商品管理：SPU 列表（含销量）+ SKU 展开明细 + 改价进审批 + 上下架 + 商品知识同步。
     对齐 页面设计.md §3.10 与 design.pen「商品管理-/goods」画板；
     后端不可用时 catch 回 mock 演示数据（页面可用性优先）。 -->
<template>
  <div class="page">
    <div v-if="demo" class="err-bar">
      <el-tag type="warning" size="small">演示数据</el-tag>
      <span class="err-text">商品接口不可用 → 已切演示数据（操作可能不落库）</span>
      <AiButton size="small" @click="reload">重试</AiButton>
    </div>

    <div class="filters">
      <AiInput v-model="keyword" placeholder="搜 SPU / 名称" class="kw" @keyup.enter="reload" />
      <el-select v-model="status" placeholder="状态" class="sel" clearable @change="reload">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <AiButton @click="reload">查询</AiButton>
      <span class="hint">Enter 亦触发查询</span>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      class="table"
      highlight-current-row
      empty-text="没有匹配的 SPU（换关键词或清空状态试试）"
      @current-change="onRowSelect"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="sku-wrap">
            <el-table :data="row.skus" size="small" class="sku-table">
              <el-table-column prop="sku_code" label="SKU 编码" min-width="140" />
              <el-table-column prop="color" label="颜色" width="70" />
              <el-table-column prop="size" label="尺码" width="60" />
              <el-table-column prop="barcode" label="条码" width="110" />
              <el-table-column label="售价" width="90">
                <template #default="s">{{ formatCents(s.row.sale_price) }}</template>
              </el-table-column>
              <el-table-column label="可售库存" width="85">
                <template #default="s">
                  <span :class="s.row.available <= 0 ? 'stock-out' : ''">
                    {{ s.row.available }}
                  </span>
                  <el-tag v-if="s.row.available <= 0" type="danger" size="small" class="stock-tag"
                    >缺货</el-tag
                  >
                </template>
              </el-table-column>
              <el-table-column prop="status_label" label="状态" width="70" />
              <el-table-column label="操作" width="150">
                <template #default="s">
                  <span v-permission="['shop', 'ops', 'admin']" class="row-ops">
                    <a class="link" @click="openPrice(s.row as SkuItem)">改价</a>
                    <a class="link" @click="changeBarcode(s.row as SkuItem)">改条码</a>
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="spu_no" label="SPU" min-width="120" />
      <el-table-column prop="name" label="名称" min-width="150" />
      <el-table-column prop="category" label="类目" width="90" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="goodsTagOf(row.status)" size="small">{{ row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sales" label="销量" width="80" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <span v-permission="['shop', 'ops', 'admin']" class="row-ops">
            <a class="link" @click="toggleStatus(row as GoodsItem)">{{
              row.status === 'on' ? '下架' : '上架'
            }}</a>
            <a class="link" @click="openPrice(row.skus?.[0] as SkuItem)">改价</a>
          </span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        @current-change="load"
        @size-change="onSizeChange"
      />
    </div>

    <!-- 颜色×尺码矩阵（抽离组件，守 400 行线） -->
    <GoodsMatrixCard :selected="selected" />

    <!-- 知识同步提示条（FR-10.1：商品变更自动同步客服知识） -->
    <div v-if="kbSync" class="kb-bar">
      <span class="kb-text">商品变更已同步客服知识（面料 / 尺码 / 价格段）</span>
      <span class="kb-meta">{{ kbSync.title }} · v{{ kbSync.version }}</span>
      <AiButton link type="primary" size="small" @click="router.push('/knowledge')">
        查看知识条目
      </AiButton>
    </div>

    <!-- 改价弹窗（抽离组件，守 400 行线） -->
    <GoodsPriceDialog v-model="priceVisible" :sku="priceSku" />

    <p class="perm-note">
      客服角色只读（goods:read）；改价 / 上下架 / 改条码需 goods:write（无权限入口自动隐藏）
    </p>
  </div>
</template>

<script setup lang="ts">
// 商品管理页（B 端）：列表 + 上下架 + SKU 行内改条码 + 改价审批 + 知识同步
// 抽离 GoodsMatrixCard（颜色×尺码矩阵）+ GoodsPriceDialog（改价弹窗），守 400 行线。
import {
  ElMessage,
  ElMessageBox,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { listGoodsApi, setGoodsStatusApi, updateSkuApi } from '@/api';
import GoodsMatrixCard from '@/components/GoodsMatrixCard.vue';
import GoodsPriceDialog from '@/components/GoodsPriceDialog.vue';
import { mockGoods } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { formatCents, goodsTagOf } from '@/types/shop';
import type { GoodsItem, KbDocInfo, SkuItem } from '@/types/shop';

const STATUS_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '在售', value: 'on' },
  { label: '已下架', value: 'off' },
  { label: '草稿', value: 'draft' },
  { label: '已归档', value: 'archived' },
] as const;

const router = useRouter();
const rows = ref<GoodsItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const demo = ref(false);
const selected = ref<GoodsItem | null>(null);
const kbSync = ref<KbDocInfo | null>(null);

const load = async () => {
  loading.value = true;
  try {
    const res = await listGoodsApi({
      keyword: keyword.value.trim(),
      status: status.value,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items ?? [];
    total.value = res.total ?? 0;
    demo.value = false;
  } catch {
    rows.value = mockGoods;
    total.value = mockGoods.length;
    demo.value = true;
    kbSync.value = null;
  } finally {
    loading.value = false;
  }
  if (!rows.value.some(g => g.id === selected.value?.id)) {
    selected.value = rows.value[0] ?? null;
  }
};

const reload = () => {
  page.value = 1;
  load();
};

const onSizeChange = () => {
  page.value = 1;
  load();
};

const onRowSelect = (row: GoodsItem | null) => {
  if (row) selected.value = row;
};

const toggleStatus = async (row: GoodsItem) => {
  const next = row.status === 'on' ? 'off' : 'on';
  if (next === 'off') {
    try {
      await ElMessageBox.confirm(`下架后买家不可购买「${row.name}」，确认下架？`, '下架确认', {
        confirmButtonText: '确认下架',
        cancelButtonText: '取消',
        type: 'warning',
      });
    } catch {
      return;
    }
  }
  try {
    const res = await setGoodsStatusApi({ productId: row.id, status: next });
    kbSync.value = res?.kb_doc ?? null;
    ElMessage.success(next === 'on' ? '已上架' : '已下架');
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  }
};

const changeBarcode = async (sku: SkuItem) => {
  try {
    const { value } = await ElMessageBox.prompt(`当前条码：${sku.barcode || '—'}`, '改条码', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /^[\w-]{0,64}$/,
      inputErrorMessage: '条码仅支持数字/字母/短横线，≤64 位',
    });
    const res = await updateSkuApi({ skuId: sku.id, barcode: value.trim() });
    kbSync.value = res?.kb_doc ?? null;
    ElMessage.success('条码已保存，商品知识已同步');
    load();
  } catch (e) {
    if (e instanceof Error) ElMessage.error(e.message);
  }
};

// 改价弹窗（v-model 控制显隐 + SKU 传入，提交审批后回调）
const priceVisible = ref(false);
const priceSku = ref<SkuItem | null>(null);

const openPrice = (sku: SkuItem | undefined) => {
  if (!sku) return;
  priceSku.value = sku;
  priceVisible.value = true;
};

onMounted(load);
</script>

<style scoped>
.page {
  padding: 16px;
}

.err-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  background: var(--reai-card);
  font-size: var(--reai-fs-body-sm);
}

.err-text {
  color: var(--reai-notice);
}

.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.kw {
  width: 220px;
}

.sel {
  width: 120px;
}

.hint {
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-soft);
}

.table {
  width: 100%;
}

.row-ops {
  display: inline-flex;
  gap: 10px;
}

.link {
  color: var(--reai-primary);
  cursor: pointer;
}

.link:hover {
  text-decoration: underline;
}

.sku-wrap {
  padding: 4px 12px;
}

.sku-table {
  width: 100%;
}

.stock-out {
  color: var(--reai-notice);
  font-weight: var(--reai-fw-semibold);
}

.stock-tag {
  margin-left: 4px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.kb-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding: 10px 14px;
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  background: var(--reai-primary-soft);
  font-size: var(--reai-fs-body-sm);
}

.kb-text {
  color: var(--reai-text-main);
}

.kb-meta {
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
}

.perm-note {
  margin: 16px 0 0;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-soft);
}
</style>
