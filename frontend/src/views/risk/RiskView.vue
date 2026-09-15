<template>
  <div class="page">
    <div class="head">
      <el-tag type="info" size="small">待实现页 · 画板先行（演示数据）</el-tag>
    </div>
    <p class="hint">禁全自动封号：拦截必进人工复核，复核结论反写源单</p>
    <el-empty v-if="!risks.length && !loading" description="暂无风险单" />
    <el-table v-loading="loading" :data="risks" style="width: 100%">
      <el-table-column prop="title" label="风险" min-width="200" />
      <el-table-column prop="graph" label="关联图谱摘要" min-width="200" />
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="RISK_TAG[s.row.status]" size="small">{{ RISK_TEXT[s.row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="s">
          <AiButton v-permission="['shop', 'admin']" link @click="passRisk(s.row)"> 通过 </AiButton>
          <AiButton v-permission="['shop', 'admin']" link type="danger" @click="blockRisk(s.row)">
            拦截（进复核）
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <h3>协同工单 · SLA {{ sla }}</h3>
    <el-table :data="tickets" style="width: 100%">
      <el-table-column prop="id" label="工单" width="130" />
      <el-table-column prop="title" label="事项" min-width="200" />
      <el-table-column prop="owner" label="当前处理" width="130" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="s">
          <AiButton v-permission="['shop', 'cs', 'admin']" link @click="closeTicket(s.row)">
            关闭回填结论
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next, total"
      @size-change="loadRisks"
      @current-change="loadRisks"
    />
  </div>
</template>

<script setup lang="ts">
// 风控工单最小可用版：拦截复核表 + 协同工单，对齐页面设计 §3.18
// 待实现页画板先行，图谱与SLA流转随后补，当前演示数据兜底
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';

const RISK_TEXT = {
  pending: '待复核',
  passed: '已通过',
  blocked: '已拦截',
} as const;

const RISK_TAG = {
  pending: 'warning',
  passed: 'success',
  blocked: 'danger',
} as const;

type RiskStatus = keyof typeof RISK_TEXT;

type RiskItem = {
  title: string;
  graph: string;
  status: RiskStatus;
};

type Ticket = {
  id: string;
  title: string;
  owner: string;
};

const risks = ref<RiskItem[]>([]);
const tickets = ref<Ticket[]>([{ id: 'WO-8812', title: '差评升级 · 跨部门流转中', owner: '运营' }]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
const sla = ref('剩余1小时20分');

const loadRisks = async () => {
  loading.value = true;
  try {
    risks.value = [{ title: '刷单嫌疑', graph: '关联3单同设备同地址', status: 'pending' }];
    total.value = risks.value.length;
  } catch {
    risks.value = [];
    ElMessage.error('加载失败，请重试');
  } finally {
    loading.value = false;
  }
};

const passRisk = (row: RiskItem) => {
  row.status = 'passed';
  ElMessage.success('已通过并反写源单（演示）');
};

const blockRisk = async (row: RiskItem) => {
  await ElMessageBox.confirm('拦截将进人工复核，不会自动封号，确认吗？', '提示');
  row.status = 'blocked';
  ElMessage.success('已拦截并进人工复核（演示）');
};

const closeTicket = async (row: Ticket) => {
  await ElMessageBox.confirm(`关闭 ${row.id} 前请确认已回填结论，确认吗？`, '提示');
  tickets.value = tickets.value.filter(t => t.id !== row.id);
  ElMessage.success('工单已关闭（演示）');
};

onMounted(() => {
  loadRisks();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
