<template>
  <div class="page">
    <div class="toolbar">
      <AiButton v-permission="['cs', 'stock', 'admin']" type="primary" @click="openCreate">
        新建售后
      </AiButton>
    </div>
    <el-empty v-if="!rows.length && !loading" description="暂无售后单" />
    <el-table v-loading="loading" :data="paged" style="width: 100%">
      <el-table-column prop="id" label="售后单ID" min-width="180" />
      <el-table-column prop="order_id" label="订单ID" min-width="180" />
      <el-table-column prop="reason" label="原因" min-width="160" />
      <el-table-column label="金额" width="120">
        <template #default="s">{{ formatCents(s.row.amount) }}</template>
      </el-table-column>
      <el-table-column prop="trace_id" label="关联会话" min-width="160" />
      <el-table-column label="证据" width="100">
        <template #default="s">{{
          s.row.evidence?.length ? `${s.row.evidence.length}张` : '-'
        }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="s">
          <el-tag :type="aftersaleTagOf(s.row.status)" size="small">{{
            s.row.status_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="s">
          <AiButton link @click="locate(s.row)">定位会话</AiButton>
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
// 售后单：列表 + 新建（关联会话 trace_id）+ 定位会话（对齐 FRD FR-10.4/页面设计 §3.13）
// TODO(P2)：ChatView 支持 ?trace= 直达指定会话，当前定位跳 /chat 并提示 trace
import { ElMessage, ElMessageBox, ElPagination, ElTag } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { createAftersaleApi, listAftersalesApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AftersaleItem } from '@/types/shop';
import { aftersaleTagOf, formatCents } from '@/types/shop';

const rows = ref<AftersaleItem[]>([]);
const loading = ref(false);
// 售后列表分页：后端暂无服务端分页，先客户端裁剪，默认 20 可切 10/20/50/100
const page = ref(1);
const size = ref(20);
const total = computed(() => rows.value.length);
const paged = computed(() =>
  rows.value.slice((page.value - 1) * size.value, page.value * size.value),
);
const dialog = ref(false);
const submitting = ref(false);
const form = ref({ order_id: '', reason: '', amount: '', trace_id: '', evidence: '' });
const router = useRouter();

const loadRows = async () => {
  loading.value = true;
  try {
    rows.value = await listAftersalesApi();
  } catch (e) {
    rows.value = [];
    ElMessage.error(e instanceof Error ? e.message : '加载售后单失败');
  } finally {
    loading.value = false;
  }
};

const onPage = (p: number) => {
  page.value = p;
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
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
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
