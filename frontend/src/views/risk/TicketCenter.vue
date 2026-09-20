<template>
  <div class="card">
    <div class="filters">
      <el-select v-model="status" placeholder="状态" class="sel" @change="reload">
        <el-option label="全部状态" value="" />
        <el-option label="进行中" value="open" />
        <el-option label="处理中" value="doing" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <AiButton @click="load">刷新工单</AiButton>
      <span class="hint">逾期（超 SLA 未关闭）标红；关闭必须回填结论</span>
    </div>
    <el-table v-loading="loading" :data="paged" class="table">
      <el-table-column prop="id" label="工单号" min-width="150" />
      <el-table-column prop="kind" label="类型" width="120" />
      <el-table-column prop="source_ref" label="来源" min-width="160" />
      <el-table-column prop="assignee" label="负责人" width="110">
        <template #default="s">{{ s.row.assignee || '—' }}</template>
      </el-table-column>
      <el-table-column label="SLA 截止" width="170">
        <template #default="s">
          <span :class="{ overdue: isOverdue(s.row as TicketItem) }">{{
            s.row.sla_due || '—'
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="s">
          <el-tag :type="ticketTagOf(s.row.status)">{{ s.row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="s">
          <AiButton
            v-permission="['cs', 'shop', 'admin']"
            link
            size="small"
            :disabled="s.row.status === 'closed'"
            @click="openTransfer(s.row as TicketItem)"
          >
            转交
          </AiButton>
          <AiButton
            v-permission="['cs', 'shop', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="s.row.status === 'closed'"
            @click="openClose(s.row as TicketItem)"
          >
            关闭
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

    <el-dialog
      :model-value="transferOpen"
      title="转交工单"
      width="400px"
      @update:model-value="transferOpen = $event"
    >
      <AiInput v-model="assignee" placeholder="新负责人" />
      <template #footer>
        <AiButton @click="transferOpen = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submitTransfer">确认</AiButton>
      </template>
    </el-dialog>
    <el-dialog
      :model-value="closeOpen"
      title="关闭工单"
      width="440px"
      @update:model-value="closeOpen = $event"
    >
      <AiInput
        v-model="conclusion"
        type="textarea"
        :rows="3"
        placeholder="结论（必填，沉淀知识）"
      />
      <template #footer>
        <AiButton @click="closeOpen = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submitClose">关闭</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 协同工单（复用既有 /tickets 端点：转交/关闭回填结论；对齐页面设计 §3.18）
// 后端暂无服务端分页：limit 50 拉取 + 客户端裁剪，与评价中心工单 Tab 同款过渡方案
import {
  ElDialog,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { closeTicketApi, listTicketsApi, transferTicketApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { TicketItem } from '@/types/shop';
import { ticketTagOf } from '@/types/shop';

const tickets = ref<TicketItem[]>([]);
const loading = ref(false);
const status = ref('');
const page = ref(1);
const size = ref(20);
const total = computed(() => tickets.value.length);
const paged = computed(() =>
  tickets.value.slice((page.value - 1) * size.value, page.value * size.value),
);
const submitting = ref(false);
const transferOpen = ref(false);
const closeOpen = ref(false);
const assignee = ref('');
const conclusion = ref('');
const active = ref<TicketItem | null>(null);

const load = async () => {
  loading.value = true;
  try {
    tickets.value = await listTicketsApi({ status: status.value });
  } catch (e) {
    tickets.value = [];
    ElMessage.error(e instanceof Error ? `加载工单失败：${e.message}` : '加载工单失败');
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
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
};

// 逾期口径：已填 SLA 截止 + 未关闭 + 已过当前时刻
const isOverdue = (row: TicketItem) =>
  Boolean(row.sla_due) && row.status !== 'closed' && new Date(row.sla_due) < new Date();

const openTransfer = (row: TicketItem) => {
  active.value = row;
  assignee.value = '';
  transferOpen.value = true;
};

const submitTransfer = async () => {
  if (!assignee.value.trim()) {
    ElMessage.warning('请填写新负责人');
    return;
  }
  submitting.value = true;
  try {
    await transferTicketApi({ id: active.value?.id ?? '', assignee: assignee.value.trim() });
    ElMessage.success('工单已转交');
    transferOpen.value = false;
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '转交失败');
  } finally {
    submitting.value = false;
  }
};

const openClose = (row: TicketItem) => {
  active.value = row;
  conclusion.value = '';
  closeOpen.value = true;
};

const submitClose = async () => {
  if (!conclusion.value.trim()) {
    ElMessage.warning('关闭工单必须回填结论');
    return;
  }
  submitting.value = true;
  try {
    await closeTicketApi({ id: active.value?.id ?? '', conclusion: conclusion.value.trim() });
    ElMessage.success('工单已关闭');
    closeOpen.value = false;
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '关闭失败');
  } finally {
    submitting.value = false;
  }
};

onMounted(() => {
  load();
});
</script>

<style scoped>
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

.overdue {
  font-weight: 600;
  color: var(--reai-notice);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
