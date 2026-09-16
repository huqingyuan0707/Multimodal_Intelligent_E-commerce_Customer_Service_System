<!-- 对话页快捷入口三件套（尺码助手三步表单 / 查物流订单选择器 / 退换申请证据+原因，对齐页面设计 §3.1） -->
<!-- 链路：ChatView 挂载 → 尺码/物流组装成人话走 ask 事件回页面发对话（复用 RAG+编排链路）；
     退换申请直调 POST /aftersales（trace_id 关联），need_approval 提示「待客服确认」。
     口径：买家演示账号可能无 order:fulfill 权限，退换按钮走 v-permission；接口失败中文提示不静默。 -->
<template>
  <div class="quick-row">
    <AiButton @click="sizeOpen = true">尺码助手</AiButton>
    <AiButton @click="openLogistics">查物流</AiButton>
    <AiButton v-permission="'order:fulfill'" @click="afterOpen = true">退换申请</AiButton>

    <el-dialog v-model="sizeOpen" title="尺码助手" width="360px">
      <div class="form">
        <AiInput v-model="sizeForm.height" placeholder="身高（cm）" aria-label="身高" />
        <AiInput v-model="sizeForm.weight" placeholder="体重（kg）" aria-label="体重" />
        <el-radio-group v-model="sizeForm.fit">
          <el-radio value="修身">修身</el-radio>
          <el-radio value="常规">常规</el-radio>
          <el-radio value="宽松">宽松</el-radio>
        </el-radio-group>
      </div>
      <template #footer>
        <AiButton @click="submitSize">生成选码问题</AiButton>
      </template>
    </el-dialog>

    <el-dialog v-model="logiOpen" title="查物流（选择订单）" width="520px">
      <p v-if="!orders.length && !busy" class="empty">暂无订单</p>
      <table v-else class="orders">
        <thead>
          <tr>
            <th>平台单号</th>
            <th>状态</th>
            <th>金额</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id">
            <td>{{ o.outer_id }}</td>
            <td>{{ o.status_label }}</td>
            <td>￥{{ yuan(o.total) }}</td>
            <td>
              <AiButton @click="pickOrder(o)">查物流</AiButton>
            </td>
          </tr>
        </tbody>
      </table>
      <el-pagination
        v-if="ordersTotal > 20"
        layout="prev, pager, next"
        size="small"
        :total="ordersTotal"
        :page-size="20"
        :current-page="ordersPage"
        @current-change="loadOrders"
      />
    </el-dialog>

    <el-dialog v-model="afterOpen" title="退换申请" width="420px">
      <div class="form">
        <AiInput v-model="afterForm.order_id" placeholder="订单号" aria-label="订单号" />
        <AiInput
          v-model="afterForm.amountYuan"
          placeholder="退款金额（元）"
          aria-label="退款金额"
        />
        <el-input
          v-model="afterForm.reason"
          type="textarea"
          :rows="2"
          maxlength="200"
          placeholder="问题描述（如：开线/色差，附瑕疵图更佳）"
          aria-label="问题描述"
        />
        <el-input
          v-model="afterForm.evidenceNote"
          placeholder="证据说明（可选，可先传图再发对话）"
          aria-label="证据说明"
        />
      </div>
      <template #footer>
        <AiButton :loading="busy" @click="submitAfter">提交申请</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { createAftersaleApi, listOrdersApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const emit = defineEmits(['ask', 'notice']);

const sizeOpen = ref(false);
const logiOpen = ref(false);
const afterOpen = ref(false);
const busy = ref(false);

// 尺码助手：身高/体重/版型三步（合成自然语言问题走 RAG，尺码指南在知识库内）
const sizeForm = reactive({ height: '', weight: '', fit: '常规' });
const submitSize = () => {
  if (!sizeForm.height.trim() || !sizeForm.weight.trim()) {
    ElMessage.warning('请填写身高与体重');
    return;
  }
  emit(
    'ask',
    `我身高${sizeForm.height}cm、体重${sizeForm.weight}kg，偏好${sizeForm.fit}版型，选什么码`,
  );
  sizeOpen.value = false;
};

// 查物流：订单选择器（服务端分页默认 20），选中后组装「订单X物流到哪了」走编排 logistics.query
type OrderRow = { id: string; outer_id: string; status_label: string; total: number };
const orders = ref<OrderRow[]>([]);
const ordersTotal = ref(0);
const ordersPage = ref(1);

const loadOrders = async (page = 1) => {
  busy.value = true;
  try {
    const data = (await listOrdersApi({ page, size: 20 })) as { items: OrderRow[]; total: number };
    orders.value = data.items;
    ordersTotal.value = data.total;
    ordersPage.value = page;
  } catch (e) {
    ElMessage.error((e as Error).message || '订单加载失败');
  } finally {
    busy.value = false;
  }
};

const openLogistics = () => {
  logiOpen.value = true;
  loadOrders();
};

const pickOrder = (row: OrderRow) => {
  emit('ask', `订单 ${row.outer_id}（单号 ${row.id}）物流到哪了`);
  logiOpen.value = false;
};

// 退换申请：原因 + 退款金额（元，提交转分）+ 订单号；提交即进审批链路（超阈值 need_approval）
const afterForm = reactive({ order_id: '', reason: '', amountYuan: '', evidenceNote: '' });
const submitAfter = async () => {
  const cents = Math.round(Number(afterForm.amountYuan || 0) * 100);
  if (!afterForm.order_id.trim() || !afterForm.reason.trim() || cents <= 0) {
    ElMessage.warning('订单号、原因与退款金额（元）都必填');
    return;
  }
  busy.value = true;
  try {
    const data = (await createAftersaleApi({
      order_id: afterForm.order_id.trim(),
      reason: `${afterForm.reason}（补充：${afterForm.evidenceNote || '无'}）`,
      amount: cents,
      trace_id: `chat-${Date.now()}`,
      evidence: afterForm.evidenceNote ? [afterForm.evidenceNote] : [],
    })) as { need_approval: boolean; aftersale_id: string };
    afterOpen.value = false;
    emit(
      'notice',
      data.need_approval
        ? `退换申请已提交（单号 ${data.aftersale_id}），金额超阈值转人工审批，待客服确认后生效`
        : `退换申请已提交（单号 ${data.aftersale_id}），待客服确认`,
    );
  } catch (e) {
    ElMessage.error((e as Error).message || '退换申请提交失败');
  } finally {
    busy.value = false;
  }
};

const yuan = (cents: number) => (cents / 100).toFixed(2);
</script>

<style scoped>
.quick-row {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
  flex-wrap: wrap;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.orders {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
}

.orders th,
.orders td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid var(--reai-border);
}

.empty {
  color: var(--reai-text-muted);
}
</style>
