<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane label="差评盘" name="bad">
        <div class="toolbar">
          <AiButton @click="loadBad">刷新差评</AiButton>
          <span class="hint">2 小时 SLA：超时的行会标红，请优先处理</span>
        </div>
        <el-empty v-if="!bads.length && !loading" description="暂无差评" />
        <el-table v-loading="loading" :data="pagedBads" style="width: 100%">
          <el-table-column prop="platform" label="平台" width="100" />
          <el-table-column prop="content" label="内容" min-width="220" />
          <el-table-column label="状态" width="100">
            <template #default="s">
              <el-tag :type="s.row.replied ? 'success' : 'danger'">
                {{ s.row.replied ? '已回复' : '待回复' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="工单" width="140">
            <template #default="s">{{ s.row.ticket_id || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="s">
              <AiButton link @click="openReply(s.row)">回复</AiButton>
              <AiButton link @click="makeTicket(s.row)">建工单</AiButton>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            :current-page="badPage"
            :page-size="badSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="badTotal"
            layout="sizes, prev, pager, next, total"
            @current-change="onBadPage"
            @size-change="onBadSize"
          />
        </div>
      </el-tab-pane>
      <el-tab-pane label="工单中心" name="tickets">
        <div class="toolbar">
          <AiButton @click="loadTickets">刷新工单</AiButton>
          <span class="hint">逾期（超 sla_due 未关闭）标红；关闭必须回填结论</span>
        </div>
        <el-empty v-if="!tickets.length && !tLoading" description="暂无工单" />
        <el-table v-loading="tLoading" :data="pagedTickets" style="width: 100%">
          <el-table-column prop="kind" label="类型" width="120" />
          <el-table-column prop="source_ref" label="来源" min-width="160" />
          <el-table-column prop="assignee" label="负责人" width="120" />
          <el-table-column label="状态" width="100">
            <template #default="s">
              <el-tag :type="ticketTagOf(s.row.status)">{{ s.row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240">
            <template #default="s">
              <AiButton link @click="openTransfer(s.row)">转交</AiButton>
              <AiButton link @click="openClose(s.row)">关闭</AiButton>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            :current-page="ticketPage"
            :page-size="ticketSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="ticketTotal"
            layout="sizes, prev, pager, next, total"
            @current-change="onTicketPage"
            @size-change="onTicketSize"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="replyDialog" title="回复评价" width="440px">
      <AiInput v-model="replyText" type="textarea" :rows="3" placeholder="回复内容" />
      <template #footer>
        <AiButton @click="replyDialog = false">取消</AiButton>
        <AiButton type="primary" :loading="replying" @click="submitReply">发送</AiButton>
      </template>
    </el-dialog>
    <el-dialog v-model="transferDialog" title="转交工单" width="400px">
      <AiInput v-model="assignee" placeholder="新负责人" />
      <template #footer>
        <AiButton @click="transferDialog = false">取消</AiButton>
        <AiButton type="primary" :loading="tSubmitting" @click="submitTransfer">确认</AiButton>
      </template>
    </el-dialog>
    <el-dialog v-model="closeDialog" title="关闭工单" width="440px">
      <AiInput
        v-model="conclusion"
        type="textarea"
        :rows="3"
        placeholder="结论（必填，沉淀知识）"
      />
      <template #footer>
        <AiButton @click="closeDialog = false">取消</AiButton>
        <AiButton type="primary" :loading="tSubmitting" @click="submitClose">关闭</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 评价工单：差评盘（回复/一键建工单 SLA 2h）+ 工单中心（转交/关闭回填结论）
// 对齐 FRD FR-10.8/FR-12.3、页面设计 §3.17/§3.18；独立 /tickets 页为 P2，本页先行承载
import { ElMessage, ElMessageBox, ElPagination } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import {
  closeTicketApi,
  createReviewTicketApi,
  listReviewsApi,
  listTicketsApi,
  replyReviewApi,
  transferTicketApi,
} from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { ReviewItem, TicketItem } from '@/types/shop';
import { ticketTagOf } from '@/types/shop';

const tab = ref('bad');
const bads = ref<ReviewItem[]>([]);
const loading = ref(false);
// 差评/工单双表分页：后端暂无服务端分页，先客户端裁剪，默认 20 可切 10/20/50/100
const badPage = ref(1);
const badSize = ref(20);
const badTotal = computed(() => bads.value.length);
const pagedBads = computed(() =>
  bads.value.slice((badPage.value - 1) * badSize.value, badPage.value * badSize.value),
);
const replyDialog = ref(false);
const replying = ref(false);
const replyText = ref('');
const replyRow = ref<ReviewItem | null>(null);
const tickets = ref<TicketItem[]>([]);
const tLoading = ref(false);
const ticketPage = ref(1);
const ticketSize = ref(20);
const ticketTotal = computed(() => tickets.value.length);
const pagedTickets = computed(() =>
  tickets.value.slice((ticketPage.value - 1) * ticketSize.value, ticketPage.value * ticketSize.value),
);
const tSubmitting = ref(false);
const transferDialog = ref(false);
const closeDialog = ref(false);
const assignee = ref('');
const conclusion = ref('');
const activeTicket = ref<TicketItem | null>(null);

const loadBad = async () => {
  loading.value = true;
  try {
    bads.value = await listReviewsApi({ level: 'bad' });
  } catch (e) {
    bads.value = [];
    ElMessage.error(e instanceof Error ? e.message : '加载差评失败');
  } finally {
    loading.value = false;
  }
};

const onBadPage = (p: number) => {
  badPage.value = p;
};

const onBadSize = (s: number) => {
  badSize.value = s;
  badPage.value = 1;
};

const onTicketPage = (p: number) => {
  ticketPage.value = p;
};

const onTicketSize = (s: number) => {
  ticketSize.value = s;
  ticketPage.value = 1;
};

const openReply = (row: ReviewItem) => {
  replyRow.value = row;
  replyText.value = '';
  replyDialog.value = true;
};

const submitReply = async () => {
  if (!replyRow.value || !replyText.value.trim()) {
    ElMessage.warning('请填写回复内容');
    return;
  }
  replying.value = true;
  try {
    await replyReviewApi({ id: replyRow.value.id, reply: replyText.value.trim() });
    ElMessage.success('回复成功');
    replyDialog.value = false;
    await loadBad();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '回复失败');
  } finally {
    replying.value = false;
  }
};

const makeTicket = async (row: ReviewItem) => {
  await ElMessageBox.confirm('为该差评建协同工单（SLA 2h）吗？', '提示');
  try {
    await createReviewTicketApi({ id: row.id });
    ElMessage.success('工单已创建，请到工单中心跟进');
    await loadBad();
    await loadTickets();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '建单失败');
  }
};

const loadTickets = async () => {
  tLoading.value = true;
  try {
    tickets.value = await listTicketsApi();
  } catch (e) {
    tickets.value = [];
    ElMessage.error(e instanceof Error ? e.message : '加载工单失败');
  } finally {
    tLoading.value = false;
  }
};

const openTransfer = (row: TicketItem) => {
  activeTicket.value = row;
  assignee.value = '';
  transferDialog.value = true;
};

const submitTransfer = async () => {
  if (!activeTicket.value || !assignee.value) {
    ElMessage.warning('请填写新负责人');
    return;
  }
  tSubmitting.value = true;
  try {
    await transferTicketApi({ id: activeTicket.value.id, assignee: assignee.value });
    ElMessage.success('转交成功');
    transferDialog.value = false;
    await loadTickets();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '转交失败');
  } finally {
    tSubmitting.value = false;
  }
};

const openClose = (row: TicketItem) => {
  activeTicket.value = row;
  conclusion.value = '';
  closeDialog.value = true;
};

const submitClose = async () => {
  if (!activeTicket.value || !conclusion.value.trim()) {
    ElMessage.warning('关闭结论不能为空');
    return;
  }
  tSubmitting.value = true;
  try {
    await closeTicketApi({ id: activeTicket.value.id, conclusion: conclusion.value.trim() });
    ElMessage.success('工单已关闭');
    closeDialog.value = false;
    await loadTickets();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '关闭失败');
  } finally {
    tSubmitting.value = false;
  }
};

onMounted(() => {
  loadBad();
  loadTickets();
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
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
