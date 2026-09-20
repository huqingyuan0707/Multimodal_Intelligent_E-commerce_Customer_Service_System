<template>
  <div class="page">
    <!-- 拦截复核（对齐画板 risk-table：通过/拦截 · 禁全自动封号 · 服务端分页 默认20） -->
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
        <el-select v-model="kind" placeholder="事件类型" class="sel" @change="reload">
          <el-option label="全部类型" value="" />
          <el-option v-for="(label, key) in KIND_OPTIONS" :key="key" :label="label" :value="key" />
        </el-select>
        <AiButton @click="reload">查询</AiButton>
        <span class="hint">本页待复核 {{ pendingCount }} 条 · 拦截必填理由，禁全自动封号</span>
      </div>
      <el-table v-loading="loading" :data="rows" class="table">
        <el-table-column prop="id" label="事件号" min-width="150" />
        <el-table-column prop="user_ref" label="涉及用户" min-width="120" />
        <el-table-column label="类型" width="100">
          <template #default="s">{{ s.row.kind_label }}</template>
        </el-table-column>
        <el-table-column label="图谱摘要" min-width="220">
          <template #default="s">
            <span class="detail">{{ detailText(s.row.detail) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="s">
            <el-tag :type="riskTagOf(s.row.status)">{{ s.row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="复核人" width="100">
          <template #default="s">{{ s.row.reviewer || '—' }}</template>
        </el-table-column>
        <el-table-column label="复核理由" min-width="160">
          <template #default="s">{{ s.row.reason || '—' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="操作" width="140">
          <template #default="s">
            <AiButton
              v-permission="['shop', 'admin']"
              link
              type="success"
              size="small"
              :disabled="!s.row.reviewable"
              @click="pass(s.row as RiskEventItem)"
            >
              通过
            </AiButton>
            <AiButton
              v-permission="['shop', 'admin']"
              link
              type="danger"
              size="small"
              :disabled="!s.row.reviewable"
              @click="block(s.row as RiskEventItem)"
            >
              拦截
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

    <!-- 协同工单（对齐画板 risk-ticket，复用既有 /tickets 端点） -->
    <TicketCenter />
  </div>
</template>

<script setup lang="ts">
// 风控工单：拦截复核（通过/拦截，人工留痕禁全自动封号）+ 协同工单（TicketCenter 子组件）
// 对齐页面设计 §3.18 / 画板 风控工单-/risk；复核按钮仅 shop/admin（cs 只读），重复复核后端 3005 兜底
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
import { blockRiskEventApi, listRiskEventsApi, passRiskEventApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { RiskEventItem } from '@/types/shop';
import { riskTagOf } from '@/types/shop';
import TicketCenter from './TicketCenter.vue';

// 筛选枚举（中文口径与后端 STATUS_LABELS/KIND_LABELS 一致，行内展示走后端 *_label）
const STATUS_OPTIONS = { pending: '待复核', passed: '已放行', blocked: '已拦截' } as const;
const KIND_OPTIONS = {
  order_risk: '订单风险',
  refund_abuse: '退款异常',
  account_link: '账号关联',
  coupon_abuse: '券滥用',
} as const;

const rows = ref<RiskEventItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const status = ref('');
const kind = ref('');
const loading = ref(false);
const pendingCount = ref(0);

// 图谱摘要只读展示：键值对拼接，对象/数组折叠为 JSON 串（脏数据按空串兜底，不炸列表）
const detailText = (detail: object) => {
  const entries = Object.entries(detail ?? {});
  if (!entries.length) {
    return '—';
  }
  return entries
    .map(([key, value]) => {
      const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
      return `${key}: ${text}`;
    })
    .join('；');
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listRiskEventsApi({
      status: status.value,
      kind: kind.value,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    pendingCount.value = res.pending ?? 0;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    pendingCount.value = 0;
    ElMessage.error(e instanceof Error ? `加载风控事件失败：${e.message}` : '加载风控事件失败');
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

// 复核放行（理由可空）；重复复核后端 3005 兜底
const pass = async (row: RiskEventItem) => {
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt(
      `放行 ${row.user_ref} 的${row.kind_label}事件（理由可留空，结论留痕）`,
      '复核放行',
    ));
  } catch {
    return;
  }
  try {
    await passRiskEventApi({ id: row.id, reason: (reason ?? '').trim() });
    ElMessage.success('已放行');
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '复核失败');
  }
};

// 复核拦截：理由必填（合规留痕）；只落结论不封号，处置走人工流程
const block = async (row: RiskEventItem) => {
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt(
      `拦截 ${row.user_ref} 的${row.kind_label}事件（理由必填，合规留痕）`,
      '复核拦截',
      { inputValidator: (v: string) => (v ?? '').trim().length > 0 || '拦截理由必填' },
    ));
  } catch {
    return;
  }
  try {
    await blockRiskEventApi({ id: row.id, reason: reason.trim() });
    ElMessage.success('已拦截并留痕，处置请走人工流程');
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '复核失败');
  }
};

onMounted(() => {
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

.detail {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
