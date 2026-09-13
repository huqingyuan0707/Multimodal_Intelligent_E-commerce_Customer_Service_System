<template>
  <div class="page">
    <div class="head">
      <h2>商品管理</h2>
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
    </div>
    <div class="filters">
      <AiInput v-model="keyword" placeholder="搜 SPU/名称" class="kw" @keyup.enter="reload" />
      <el-select v-model="status" placeholder="状态" class="sel" @change="reload">
        <el-option
          v-for="o in STATUS_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
      <AiButton @click="reload">查询</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" class="table">
      <el-table-column type="expand">
        <template #default="props">
          <el-table :data="props.row.skus" size="small">
            <el-table-column prop="sku_code" label="SKU 编码" />
            <el-table-column prop="color" label="颜色" width="70" />
            <el-table-column prop="size" label="尺码" width="70" />
            <el-table-column prop="barcode" label="条码" />
            <el-table-column label="售价">
              <template #default="s">{{ formatCents(s.row.sale_price) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="s">
                <el-tag :type="goodsTagOf(s.row.status)" size="small">{{ s.row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="170">
              <template #default="s">
                <el-button
                  v-permission="['shop', 'ops', 'admin']"
                  link
                  type="primary"
                  size="small"
                  @click="changePrice(s.row as SkuItem)"
                >
                  改价
                </el-button>
                <el-button
                  v-permission="['shop', 'ops', 'admin']"
                  link
                  type="primary"
                  size="small"
                  @click="changeBarcode(s.row as SkuItem)"
                >
                  改条码
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-table-column>
      <el-table-column prop="spu_no" label="SPU" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="category" label="类目" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="s">
          <el-tag :type="goodsTagOf(s.row.status)" size="small">{{ s.row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="s">
          <el-button
            v-permission="['shop', 'ops', 'admin']"
            link
            type="primary"
            size="small"
            @click="toggleStatus(s.row as GoodsItem)"
          >
            {{ s.row.status === 'on' ? '下架' : '上架' }}
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
// 商品管理（SPU 列表 + SKU 矩阵展开 + 改价进审批 + 上下架，对齐页面设计 §3.10；后端未就绪回 mock）
import { ElMessage, ElMessageBox, ElPagination, ElSelect, ElOption, ElTable, ElTableColumn, ElTag } from 'element-plus';
import { onMounted, ref } from 'vue';
import { listGoodsApi, setGoodsStatusApi, submitPriceChangeApi, updateSkuApi } from '@/api';
import { mockGoods } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { formatCents, goodsTagOf } from '@/types/shop';
import type { GoodsItem, SkuItem } from '@/types/shop';

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'on', label: '在售' },
  { value: 'off', label: '已下架' },
  { value: 'draft', label: '草稿' },
];

const rows = ref<GoodsItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const demo = ref(false);

const load = async () => {
  loading.value = true;
  try {
    const res = await listGoodsApi({
      keyword: keyword.value.trim(),
      status: status.value,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    demo.value = false;
  } catch {
    const kw = keyword.value.trim();
    rows.value = mockGoods.filter(
      (g) =>
        (!status.value || g.status === status.value) &&
        (!kw || g.name.includes(kw) || g.spu_no.includes(kw)),
    );
    total.value = rows.value.length;
    demo.value = true;
  } finally {
    loading.value = false;
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

// 上下架：下架二次确认（对齐后端注释），上架直接执行
const toggleStatus = async (row: GoodsItem) => {
  const toOff = row.status === 'on';
  if (toOff) {
    try {
      await ElMessageBox.confirm('下架后买家不可见，确定下架吗？', '下架确认');
    } catch {
      return;
    }
  }
  try {
    await setGoodsStatusApi({ productId: row.id, status: toOff ? 'off' : 'on' });
    ElMessage.success(toOff ? '已下架' : '已上架');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  }
};

// 改价恒进审批：此刻价格不变，审批通过后自动生效（资损红线）
const changePrice = async (sku: SkuItem) => {
  let value: string;
  try {
    ({ value } = await ElMessageBox.prompt(
      `当前售价 ${formatCents(sku.sale_price)}，请输入新售价（元）`,
      '改价（将进入审批）',
    ));
  } catch {
    return;
  }
  const yuan = Number(value);
  if (!Number.isFinite(yuan) || yuan <= 0) {
    ElMessage.warning('请输入大于 0 的金额');
    return;
  }
  try {
    await submitPriceChangeApi({
      skuId: sku.id,
      newPrice: Math.round(yuan * 100),
      reason: '工作台改价',
    });
    ElMessage.success('改价已提交审批，通过后自动生效');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败');
  }
};

// SKU 行内改条码（价格不在此列，必须走审批；对齐后端 SkuUpdateRequest）
const changeBarcode = async (sku: SkuItem) => {
  let value: string;
  try {
    ({ value } = await ElMessageBox.prompt('请输入新条码', '改条码', {
      inputValue: sku.barcode,
    }));
  } catch {
    return;
  }
  if (!value.trim()) {
    ElMessage.warning('条码不能为空');
    return;
  }
  try {
    await updateSkuApi({ skuId: sku.id, barcode: value.trim() });
    ElMessage.success('条码已保存');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败');
  }
};

onMounted(() => {
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
  margin: 12px 0;
}

.kw {
  width: 240px;
}

.sel {
  width: 140px;
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
