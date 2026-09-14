<template>
  <div class="page">
    <div class="head">
      <el-tag type="info" size="small">待实现页 · 画板先行（演示数据）</el-tag>
    </div>
    <h3>供应商</h3>
    <el-empty v-if="!suppliers.length && !loading" description="暂无供应商" />
    <el-table v-loading="loading" :data="suppliers" style="width: 100%">
      <el-table-column prop="name" label="供应商" min-width="160" />
      <el-table-column prop="term" label="账期" width="110" />
      <el-table-column label="合格率" width="110">
        <template #default="s">{{ s.row.quality }}%</template>
      </el-table-column>
      <el-table-column prop="eta" label="到货ETA" width="120" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="s">
          <AiButton v-permission="['shop', 'stock', 'admin']" link @click="createOrder(s.row)">
            新建采购单
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
      @size-change="loadSuppliers"
      @current-change="loadSuppliers"
    />
    <h3>采购单 · 草稿→审批→到货→质检→入库</h3>
    <el-steps :active="2" finish-status="success" simple>
      <el-step v-for="s in steps" :key="s" :title="s" />
    </el-steps>
    <el-card class="qc" shadow="never">
      <template #header>质检卡</template>
      <p>PO-2026-091 · 针织开衫500件 · 待质检</p>
      <AiButton v-permission="['shop', 'stock', 'admin']" type="danger" @click="failQc">
        质检不合格（暂停销售+退供）
      </AiButton>
    </el-card>
    <p class="hint">到货ETA供客服承诺交期（客服侧只读）；接口与审批流待B端二期补齐</p>
  </div>
</template>

<script setup lang="ts">
// 采购协同最小可用版：供应商列表 + 采购单状态机 + 质检卡，对齐页面设计 §3.12
// 待实现页画板先行，接口与审批流随后补，当前演示数据兜底
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';

type Supplier = {
  name: string;
  term: string;
  quality: number;
  eta: string;
};

const steps = ['草稿', '审批', '到货', '质检', '入库'];
const suppliers = ref<Supplier[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);

const loadSuppliers = async () => {
  loading.value = true;
  try {
    suppliers.value = [{ name: '东莞针织厂', term: '30天', quality: 98.2, eta: '3天' }];
    total.value = suppliers.value.length;
  } catch {
    suppliers.value = [];
    ElMessage.error('加载失败，请重试');
  } finally {
    loading.value = false;
  }
};

const createOrder = (row: Supplier) => {
  ElMessage.success(`已为 ${row.name} 建采购单草稿（演示，审批流待接）`);
};

const failQc = async () => {
  await ElMessageBox.confirm('质检不合格将暂停销售并退供，确认吗？', '提示');
  ElMessage.success('已暂停销售并通知退供（演示）');
};

onMounted(() => {
  loadSuppliers();
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

.qc {
  background: var(--reai-card);
  border-color: var(--reai-border);
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
