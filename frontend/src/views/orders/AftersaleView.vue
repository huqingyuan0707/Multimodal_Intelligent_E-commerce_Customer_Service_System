<template>
  <div class="page">
    <div class="toolbar">
      <AiButton v-permission="['cs', 'stock', 'admin']" type="primary" @click="openCreate">
        新建售后
      </AiButton>
      <el-select v-model="status" placeholder="售后状态" class="sel" @change="reload">
        <el-option label="全部状态" value="" />
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-model="disposition" placeholder="质检处置" class="sel" @change="reload">
        <el-option label="全部处置" value="" />
        <el-option
          v-for="o in DISPOSITION_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
    </div>
    <el-empty v-if="!rows.length && !loading" description="暂无售后单" />
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="id" label="售后单ID" min-width="130" />
      <el-table-column prop="order_id" label="订单ID" min-width="130" />
      <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip />
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
      <el-table-column label="质检处置" width="110">
        <template #default="s">
          <el-tag :type="dispositionTagOf(s.row.disposition)" size="small">{{
            s.row.disposition_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="证据" width="120">
        <template #default="s">
          <span v-if="!s.row.evidence?.length" class="muted">-</span>
          <el-image
            v-for="(url, i) in (s.row.evidence || []).slice(0, 2)"
            :key="i"
            :src="url"
            :preview-src-list="s.row.evidence"
            :initial-index="i"
            preview-teleported
            fit="cover"
            class="thumb"
          />
          <span v-if="(s.row.evidence || []).length > 2" class="muted"
            >+{{ (s.row.evidence || []).length - 2 }}</span
          >
        </template>
      </el-table-column>
      <el-table-column label="trace_id" width="120">
        <template #default="s">
          <span class="mono">{{ s.row.trace_id || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column label="操作" width="300">
        <template #default="s">
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            size="small"
            @click="openDetail(s.row)"
          >
            详情
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            size="small"
            :disabled="!s.row.trace_id"
            @click="locate(s.row)"
          >
            定位会话
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="s.row.disposition !== 'pending'"
            @click="dispose(s.row, 'restocked')"
          >
            二次入库
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="warning"
            size="small"
            :disabled="s.row.disposition !== 'pending'"
            @click="dispose(s.row, 'scrapped')"
          >
            报损
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="danger"
            size="small"
            :disabled="s.row.disposition !== 'pending'"
            @click="dispose(s.row, 'returned')"
          >
            退供
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
    <AftersaleCreateDialog v-model="dialog" @created="loadRows" />
    <AftersaleDetailDrawer v-model="drawer" :detail="detail" @locate="locate" @dispose="dispose" />
  </div>
</template>

<script setup lang="ts">
// 售后单：服务端分页列表（真接口优先，失败置空 + 中文提示，不编造数据）+ 质检处置 + 详情抽屉
// 新建对话框拆 AftersaleCreateDialog.vue（订单远程搜索、元→分、证据图），详情拆 AftersaleDetailDrawer.vue
// 对齐 FRD FR-10.4 / 页面设计 §3.13 / API 规范 §4.7
// 红线：①处置按钮按 disposition !== pending 置灰；②报损恒进审批（sensitive），二次入库/退供直接生效；
// ③后端金额一律分，页面只收元、只展示格式化元；④列表默认 20 可切 10/20/50/100。
import {
  ElMessage,
  ElMessageBox,
  ElEmpty,
  ElImage,
  ElPagination,
  ElSelect,
  ElOption,
  ElTag,
} from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { disposeAftersaleApi, listAftersalesApi } from '@/api';
import AftersaleCreateDialog from '@/components/AftersaleCreateDialog.vue';
import AftersaleDetailDrawer from '@/components/AftersaleDetailDrawer.vue';
import AiButton from '@/shared/components/AiButton.vue';
import type { AftersaleItem } from '@/types/shop';
import { aftersaleTagOf, dispositionTagOf, formatCents } from '@/types/shop';

const STATUS_OPTIONS = [
  { value: 'pending', label: '待处理' },
  { value: 'approving', label: '审批中' },
  { value: 'done', label: '已完成' },
];

const DISPOSITION_OPTIONS = [
  { value: 'restocked', label: '二次入库' },
  { value: 'scrapped', label: '报损' },
  { value: 'returned', label: '退供' },
];

const rows = ref<AftersaleItem[]>([]);
const loading = ref(false);
// 售后列表服务端分页（前端红线：默认 20，可切 10/20/50/100）
const page = ref(1);
const size = ref(20);
const total = ref(0);
const status = ref('');
const disposition = ref('');
const dialog = ref(false);
const drawer = ref(false);
const detail = ref<AftersaleItem | null>(null);
const router = useRouter();

const loadRows = async () => {
  loading.value = true;
  try {
    const res = await listAftersalesApi({
      status: status.value || undefined,
      disposition: disposition.value || undefined,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    // 后端不可用 → 置空列表 + 中文可操作提示，不编造数据
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载售后单失败：${e.message}` : '加载售后单失败');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  loadRows();
};

const onPage = (p: number) => {
  page.value = p;
  loadRows();
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  loadRows();
};

const DISPOSE_LABEL = { restocked: '二次入库', scrapped: '报损', returned: '退供' } as const;

// 质检处置：报损转审批，其余直接生效；已处置/审批中由后端再校验（前端只按 disposition 置灰）
const dispose = async (row: AftersaleItem, kind: 'restocked' | 'scrapped' | 'returned') => {
  const label = DISPOSE_LABEL[kind];
  try {
    await ElMessageBox.confirm(
      `确认对售后单 ${row.id} 执行「${label}」处置吗？${
        kind === 'scrapped' ? '报损为敏感操作，将进入审批流。' : ''
      }`,
      '质检处置',
    );
  } catch {
    return;
  }
  try {
    const res = await disposeAftersaleApi({ aftersaleId: row.id, disposition: kind });
    if (res.need_approval) {
      ElMessage.warning(
        `报损已转审批${res.approval_id ? `（${res.approval_id}）` : ''}，批准后生效`,
      );
    } else {
      ElMessage.success(`处置成功：${res.disposition_label}`);
    }
    await loadRows();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '处置失败');
  }
};

const openCreate = () => {
  dialog.value = true;
};

const openDetail = (row: AftersaleItem) => {
  detail.value = { ...row };
  drawer.value = true;
};

const locate = (row: AftersaleItem) => {
  if (!row.trace_id) {
    ElMessage.warning('该售后单未关联客服会话');
    return;
  }
  ElMessage.success(`关联会话 trace：${row.trace_id}`);
  router.push({ path: '/chat', query: { trace: row.trace_id } });
};

onMounted(() => {
  loadRows();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.sel {
  width: 140px;
}

.order-sel {
  width: 100%;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.muted {
  color: var(--reai-text-muted);
  font-size: var(--reai-fs-caption);
}

.mono {
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-caption);
}

.thumb {
  width: 36px;
  height: 36px;
  margin-right: 4px;
  border-radius: 4px;
}
</style>
