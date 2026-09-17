<template>
  <el-dialog v-model="visible" title="新建售后单" width="520px">
    <el-form :model="form" label-width="90px">
      <el-form-item label="关联订单">
        <el-select
          v-model="form.order_id"
          filterable
          remote
          :remote-method="searchOrders"
          :loading="orderLoading"
          placeholder="搜索订单（平台单号/ID）"
          class="order-sel"
          @change="onPickOrder"
        >
          <el-option
            v-for="o in orderOptions"
            :key="o.id"
            :label="`${o.outer_id || o.id} · ${o.status_label}`"
            :value="o.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="原因">
        <AiInput v-model="form.reason" placeholder="如：袖口脱线" />
      </el-form-item>
      <el-form-item label="金额(元)">
        <AiInput v-model="form.amount" placeholder="0.00（超阈值自动转审批）" />
      </el-form-item>
      <el-form-item label="会话trace">
        <AiInput v-model="form.trace_id" placeholder="客服会话 trace_id（选中订单自动带出）" />
      </el-form-item>
      <el-form-item label="证据图">
        <AiInput v-model="form.evidence" placeholder="图片 URL，逗号分隔，可空" />
      </el-form-item>
    </el-form>
    <template #footer>
      <AiButton @click="visible = false">取消</AiButton>
      <AiButton type="primary" :loading="submitting" @click="submit">提交</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 新建售后单对话框：订单远程搜索（仅展示可发起售后的订单，选中带出 trace_id）+ 金额元→分 + 证据图
// 对齐 API 规范 §4.7 POST /aftersales；创建成功后 emit('created') 由调用方刷新列表
import { ElMessage, ElMessageBox, ElOption, ElSelect } from 'element-plus';
import { ref, watch } from 'vue';
import { createAftersaleApi, listOrdersApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { OrderItem } from '@/types/shop';

const emit = defineEmits(['created']);
const visible = defineModel<boolean>('modelValue', { required: true });

const form = ref({ order_id: '', reason: '', amount: '', trace_id: '', evidence: '' });
const orderOptions = ref<OrderItem[]>([]);
const orderLoading = ref(false);
const submitting = ref(false);

const searchOrders = async (kw: string) => {
  orderLoading.value = true;
  try {
    const res = await listOrdersApi({ keyword: kw.trim(), page: 1, size: 20 });
    orderOptions.value = res.items.filter(o => o.allowed_actions?.includes('aftersale'));
  } catch (e) {
    orderOptions.value = [];
    ElMessage.error(e instanceof Error ? `搜索订单失败：${e.message}` : '搜索订单失败');
  } finally {
    orderLoading.value = false;
  }
};

const onPickOrder = (orderId: string) => {
  const picked = orderOptions.value.find(o => o.id === orderId);
  if (picked?.trace_id) {
    form.value.trace_id = picked.trace_id;
  }
};

watch(visible, open => {
  if (open) {
    form.value = { order_id: '', reason: '', amount: '', trace_id: '', evidence: '' };
    orderOptions.value = [];
    searchOrders('');
  }
});

const submit = async () => {
  if (!form.value.order_id) {
    ElMessage.warning('请先选择关联订单');
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
    visible.value = false;
    emit('created');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
};
</script>

<style scoped>
.order-sel {
  width: 100%;
}
</style>
