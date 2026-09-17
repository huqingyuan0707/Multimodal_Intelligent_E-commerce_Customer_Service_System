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
      <el-table-column prop="id" label="售后单ID" min-width="150" />
      <el-table-column prop="order_id" label="订单ID" min-width="150" />
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
      <el-table-column label="质检处置" width="110">
        <template #default="s">
          <el-tag :type="dispositionTagOf(s.row.disposition)" size="small">{{
            s.row.disposition_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280">
        <template #default="s">
          <AiButton v-permission="['cs', 'stock', 'admin']" link @click="locate(s.row)">
            定位会话
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="primary"
            :disabled="s.row.disposition !== 'pending'"
            @click="dispose(s.row, 'restocked')"
          >
            二次入库
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="warning"
            :disabled="s.row.disposition !== 'pending'"
            @click="dispose(s.row, 'scrapped')"
          >
            报损
          </AiButton>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            type="danger"
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
    <el-dialog v-model="dialog" title="新建售后单" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="订单ID">
          <AiInput v-model="form.order_id" placeholder="sales_orders.id" />
        </el-form-item>
        <el-form-item label="原因">
          <AiInput v-model="form.reason" placeholder="如：袖口脱线" />
        </el-form-item>
        <el-form-item label="金额(元)">
          <AiInput v-model="form.amount" placeholder="0.00" />
        </el-form-item>
        <el-form-item label="会话trace">
          <AiInput v-model="form.trace_id" placeholder="客服会话 trace_id（可空）" />
        </el-form-item>
        <el-form-item label="证据图">
          <AiInput v-model="form.evidence" placeholder="图片 URL，逗号分隔，可空" />
        </el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="close">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">提交</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 售后单：服务端分页列表 + 新建（关联会话 trace_id）+ 质检处置（二次入库/报损/退供，对齐 FRD FR-10.4/页面设计 §3.13）
// 处置红线：报损恒进审批（sensitive），二次入库/退供直接生效；已处置的售后单按钮置灰（disposition !== pending）
import { ElMessage, ElMessageBox, ElPagination, ElTag } from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { createAftersaleApi, disposeAftersaleApi, listAftersalesApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
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
// 售后列表服务端分页（前端红线：列表页必须服务端分页，默认 20 可切 10/20/50/100）
const page = ref(1);
const size = ref(20);
const total = ref(0);
const status = ref('');
const disposition = ref('');
const dialog = ref(false);
const submitting = ref(false);
const form = ref({ order_id: '', reason: '', amount: '', trace_id: '', evidence: '' });
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
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载售后单失败');
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

// 质检处置（退货质检 → 二次入库/报损/退供）：报损转审批，其余直接生效
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
  form.value = { order_id: '', reason: '', amount: '', trace_id: '', evidence: '' };
  dialog.value = true;
};

const close = () => {
  dialog.value = false;
};

const submit = async () => {
  if (!form.value.order_id) {
    ElMessage.warning('请填写订单ID');
    return;
  }
  try {
    await ElMessageBox.confirm('确认创建售后单吗？', '提示');
  } catch {
    return;
  }
  submitting.value = true;
  try {
    // 后端金额一律分，页面禁止裸展示/提交分：元→分；证据图按逗号/空格/换行切分
    const cents = Math.round(Number(form.value.amount || 0) * 100);
    const evidence = form.value.evidence
      .split(/[,，\s\n]+/)
      .map(u => u.trim())
      .filter(Boolean);
    const res = await createAftersaleApi({
      order_id: form.value.order_id,
      reason: form.value.reason,
      amount: cents,
      trace_id: form.value.trace_id,
      evidence,
    });
    if (res.need_approval) {
      ElMessage.warning(
        `退款超阈值，已转审批${res.approval_id ? `（${res.approval_id}）` : ''}，批准后生效`,
      );
    } else {
      ElMessage.success('售后单已创建');
    }
    dialog.value = false;
    await loadRows();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
