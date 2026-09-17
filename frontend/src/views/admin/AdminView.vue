<template>
  <div class="page">
    <div class="cards">
      <el-card class="card" shadow="never">租户 {{ overview.tenant_total }}</el-card>
      <el-card class="card" shadow="never">用户 {{ overview.user_total }}</el-card>
      <el-card class="card" shadow="never">非正常租户 {{ overview.suspended }}</el-card>
      <el-card class="card" shadow="never">审计 {{ overview.audit_total }}</el-card>
    </div>
    <el-tabs v-model="tab">
      <el-tab-pane label="租户" name="tenant">
        <AdminTenantPane @pick-quota="onPickQuota" @changed="loadOverview" />
      </el-tab-pane>
      <el-tab-pane label="配额" name="quota">
        <AdminQuotaPane ref="quotaRef" />
      </el-tab-pane>
      <el-tab-pane label="用户角色" name="user">
        <AdminUserPane />
      </el-tab-pane>
      <el-tab-pane label="审计" name="audit">
        <AdminAuditPane />
      </el-tab-pane>
      <el-tab-pane label="密钥" name="apikey">
        <AdminApiKeyPane />
      </el-tab-pane>
      <el-tab-pane label="SLO" name="slo">
        <AdminSloPane />
      </el-tab-pane>
      <el-tab-pane label="消息" name="notify">
        <AdminNotifyPane />
      </el-tab-pane>
      <el-tab-pane label="组织" name="org">
        <AdminOrgPane />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// 管理后台壳：概览指标卡 + 八窗格编排（租户/配额/用户/审计 + 密钥/SLO/消息/组织），数据加载下沉各窗格
// 对齐 FRD FR-8/FR-12.2/FR-12.4、页面设计 §3.8 + §3.19、API 规范 §4.9
import { ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { getAdminOverviewApi } from '@/api';
import AdminApiKeyPane from '@/components/AdminApiKeyPane.vue';
import AdminAuditPane from '@/components/AdminAuditPane.vue';
import AdminNotifyPane from '@/components/AdminNotifyPane.vue';
import AdminOrgPane from '@/components/AdminOrgPane.vue';
import AdminQuotaPane from '@/components/AdminQuotaPane.vue';
import AdminSloPane from '@/components/AdminSloPane.vue';
import AdminTenantPane from '@/components/AdminTenantPane.vue';
import AdminUserPane from '@/components/AdminUserPane.vue';
import type { AdminOverview, TenantItem } from '@/types/admin';

const tab = ref('tenant');
const overview = ref<AdminOverview>({
  tenant_total: 0,
  user_total: 0,
  suspended: 0,
  audit_total: 0,
});
const quotaRef = ref<{ setTenant: (c: string, t: number, cc: number) => unknown } | null>(null);

const loadOverview = async () => {
  try {
    overview.value = await getAdminOverviewApi();
  } catch (e) {
    overview.value = { tenant_total: 0, user_total: 0, suspended: 0, audit_total: 0 };
    ElMessage.error(e instanceof Error ? `加载概览失败：${e.message}` : '加载概览失败');
  }
};

const onPickQuota = (row: TenantItem) => {
  tab.value = 'quota';
  quotaRef.value?.setTenant(row.code, row.quota_tokens, row.quota_concurrency);
};

onMounted(() => {
  loadOverview();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.card {
  background: var(--reai-card);
  border-color: var(--reai-border);
}
</style>
