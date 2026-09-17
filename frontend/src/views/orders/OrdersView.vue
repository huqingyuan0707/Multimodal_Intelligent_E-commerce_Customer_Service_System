<template>
  <div class="page">
    <div class="head">
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
    </div>
    <div class="filters">
      <AiInput v-model="keyword" placeholder="搜平台单号" class="kw" @keyup.enter="reload" />
      <el-select v-model="status" placeholder="状态" class="sel" @change="reload">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <AiButton @click="reload">查询</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" class="table">
      <el-table-column prop="outer_id" label="平台单号" />
      <el-table-column prop="platform" label="平台" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="s">
          <el-tag :type="orderTagOf(s.row.status)" size="small">{{ s.row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="金额" width="110">
        <template #default="s">{{ formatCents(s.row.total) }}</template>
      </el-table-column>
      <el-table-column label="面单" width="200">
        <template #default="s">{{ waybill(s.row as OrderItem) }}</template>
      </el-table-column>
      <el-table-column label="trace_id" width="130">
        <template #default="s">
          <span class="mono">{{ s.row.trace_id || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230">
        <template #default="s">
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="!s.row.allowed_actions.includes('ship')"
            @click="ship(s.row as OrderItem)"
          >
            发货
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="!s.row.allowed_actions.includes('confirm')"
            @click="confirm(s.row as OrderItem)"
          >
            签收
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="!s.row.allowed_actions.includes('aftersale')"
            @click="aftersale(s.row as OrderItem)"
          >
            建售后
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            size="small"
            @click="openDetail(s.row as OrderItem)"
          >
            详情
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
    <el-drawer v-model="drawer" title="订单详情" size="520px">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="平台">{{ detail.platform }}</el-descriptions-item>
        <el-descriptions-item label="平台单号">{{ detail.outer_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="orderTagOf(detail.status)" size="small">{{ detail.status_label }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="金额">{{ formatCents(detail.total) }}</el-descriptions-item>
        <el-descriptions-item label="面单">{{
          detail.company && detail.tracking_no ? `${detail.company} ${detail.tracking_no}` : '-'
        }}</el-descriptions-item>
        <el-descriptions-item label="trace_id">
          <span class="mono">{{ detail.trace_id || '-' }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <div v-if="detail?.items?.length" class="sub-title">商品明细</div>
      <el-table v-if="detail?.items?.length" :data="detail.items" size="small">
        <el-table-column prop="sku_code" label="SKU" min-width="140" />
        <el-table-column prop="color" label="颜色" width="90" />
        <el-table-column prop="size" label="尺码" width="80" />
        <el-table-column prop="qty" label="数量" width="70" />
        <el-table-column label="单价" width="100">
          <template #default="s">{{ formatCents(s.row.price) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="detail?.aftersales?.length" class="sub-title">售后单</div>
      <el-table v-if="detail?.aftersales?.length" :data="detail.aftersales" size="small">
        <el-table-column prop="reason" label="原因" min-width="140" />
        <el-table-column label="金额" width="100">
          <template #default="s">{{ formatCents(s.row.amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="s">
            <el-tag :type="aftersaleTagOf(s.row.status)" size="small">{{
              s.row.status_label
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处置" width="100">
          <template #default="s">
            <el-tag :type="dispositionTagOf(s.row.disposition)" size="small">{{
              s.row.disposition_label
            }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 订单履约（平台订单镜像 + 打单发货 + 签收确认 + 建售后关联会话 trace；按钮按 allowed_actions 置灰，对齐页面设计 §3.13）
import {
  ElMessage,
  ElMessageBox,
  ElPagination,
  ElSelect,
  ElOption,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import {
  confirmOrderApi,
  createAftersaleApi,
  getOrderDetailApi,
  listOrdersApi,
  shipOrderApi,
} from '@/api';
import { mockOrders } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { aftersaleTagOf, dispositionTagOf, formatCents, orderTagOf } from '@/types/shop';
import type { OrderItem } from '@/types/shop';

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending_pay', label: '待付款' },
  { value: 'paid', label: '待发货' },
  { value: 'shipped', label: '已发货' },
  { value: 'completed', label: '已完成' },
  { value: 'aftersale', label: '售后中' },
  { value: 'closed', label: '已关闭' },
];

const rows = ref<OrderItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const demo = ref(false);

const waybill = (row: OrderItem) =>
  row.company && row.tracking_no ? `${row.company} ${row.tracking_no}` : '-';

const load = async () => {
  loading.value = true;
  try {
    const res = await listOrdersApi({
      status: status.value,
      keyword: keyword.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    demo.value = false;
  } catch {
    const kw = keyword.value.trim();
    rows.value = mockOrders.filter(
      o => (!status.value || o.status === status.value) && (!kw || o.outer_id.includes(kw)),
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

// 打单发货：快递公司 + 运单号双确认（后端校验状态机，非法报 3005）
const ship = async (row: OrderItem) => {
  let company: string;
  try {
    ({ value: company } = await ElMessageBox.prompt(
      '请输入快递公司（顺丰/中通/圆通/韵达/京东/邮政）',
      '打单发货',
    ));
  } catch {
    return;
  }
  if (!company.trim()) {
    ElMessage.warning('快递公司不能为空');
    return;
  }
  let trackingNo: string;
  try {
    ({ value: trackingNo } = await ElMessageBox.prompt('请输入运单号', '打单发货'));
  } catch {
    return;
  }
  if (!trackingNo.trim()) {
    ElMessage.warning('运单号不能为空');
    return;
  }
  try {
    await shipOrderApi({
      orderId: row.id,
      company: company.trim(),
      trackingNo: trackingNo.trim(),
    });
    ElMessage.success('发货成功，已生成面单');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发货失败');
  }
};

// 签收确认（已发货→已完成，FR-10.4 状态机「已发→签收→完成」；误签不可逆，二次确认）
const confirm = async (row: OrderItem) => {
  try {
    await ElMessageBox.confirm('确认该订单已签收吗？签收后订单转「已完成」。', '签收确认');
  } catch {
    return;
  }
  try {
    await confirmOrderApi(row.id);
    ElMessage.success('签收成功，订单已完成');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '签收失败');
  }
};

// 订单详情抽屉（面单 + 行快照 + 售后单，售后抽屉 trace 一键跳 workbench 回放）
const drawer = ref(false);
// 详情扩展后端口径（items 行快照 + aftersales 售后单，getOrderDetailApi 返回）
type OrderDetail = OrderItem & {
  items: { sku_code: string; color: string; size: string; qty: number; price: number }[];
  aftersales: {
    id: string;
    reason: string;
    amount: number;
    status: string;
    status_label: string;
    disposition: string;
    disposition_label: string;
    trace_id: string;
  }[];
};
const detail = ref<OrderDetail | null>(null);

const openDetail = async (row: OrderItem) => {
  detail.value = null;
  drawer.value = true;
  try {
    detail.value = await getOrderDetailApi(row.id);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '详情加载失败');
  }
};

// 建售后：关联会话 trace（红线：售后必须可回放到当时那轮对话）；超阈值自动转审批
const aftersale = async (row: OrderItem) => {
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt('请输入售后原因', '建售后'));
  } catch {
    return;
  }
  let amountRaw: string;
  try {
    ({ value: amountRaw } = await ElMessageBox.prompt('请输入退款金额（元，可填 0）', '建售后'));
  } catch {
    return;
  }
  const amount = Number(amountRaw);
  if (!Number.isFinite(amount) || amount < 0) {
    ElMessage.warning('金额必须为非负数');
    return;
  }
  try {
    const res = await createAftersaleApi({
      order_id: row.id,
      reason: reason.trim() || '工作台建售后',
      amount: Math.round(amount * 100),
      trace_id: row.trace_id,
    });
    if (res.need_approval) {
      ElMessage.warning(
        `退款超阈值，已转审批${res.approval_id ? `（${res.approval_id}）` : ''}，批准后生效`,
      );
    } else {
      ElMessage.success('售后单已创建');
    }
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
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

.mono {
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-caption);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.sub-title {
  margin: 12px 0 6px;
  font-weight: 500;
  font-size: var(--reai-fs-body);
  color: var(--reai-text);
}
</style>
