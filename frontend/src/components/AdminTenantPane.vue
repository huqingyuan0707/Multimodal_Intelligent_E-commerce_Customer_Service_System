<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="keyword" placeholder="搜编码/名称" clearable class="kw" />
      <AiButton @click="reload">查询</AiButton>
      <AiButton v-permission="['admin']" type="primary" @click="openCreate">新建租户</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="code" label="编码" min-width="140" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="套餐" width="100">
        <template #default="s">
          <el-tag :type="tenantPlanTagOf(s.row.plan)" size="small">{{ s.row.plan_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="tenantStatusTagOf(s.row.status)" size="small">{{
            s.row.status_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="配额(Token/并发)" min-width="160">
        <template #default="s">{{ s.row.quota_tokens }} / {{ s.row.quota_concurrency }}</template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="pick(s.row)">配额</AiButton>
          <AiButton v-permission="['admin']" link @click="toggle(s.row)">
            {{ s.row.status === 'active' ? '停服' : '恢复' }}
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
    <el-dialog v-model="dialog" title="新建租户" width="440px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="编码"><AiInput v-model="form.code" /></el-form-item>
        <el-form-item label="名称"><AiInput v-model="form.name" /></el-form-item>
        <el-form-item label="套餐"
          ><AiInput v-model="form.plan" placeholder="trial/basic/pro/enterprise"
        /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">创建</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 租户列表窗格：分页默认 20 + 新建 + 停服/恢复（危险操作 confirm），失败置空 + 中文提示
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { createTenantApi, listTenantsApi, setTenantStatusApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { tenantPlanTagOf, tenantStatusTagOf } from '@/types/admin';
import type { TenantItem } from '@/types/admin';

const emit = defineEmits(['pick-quota', 'changed']);

const rows = ref<TenantItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const loading = ref(false);
const submitting = ref(false);
const dialog = ref(false);
const form = ref({ code: '', name: '', plan: 'trial' });

const load = async () => {
  loading.value = true;
  try {
    const res = await listTenantsApi({
      keyword: keyword.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载租户失败：${e.message}` : '加载租户失败');
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
  load();
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  load();
};

const openCreate = () => {
  form.value = { code: '', name: '', plan: 'trial' };
  dialog.value = true;
};

const submit = async () => {
  if (!form.value.code.trim() || !form.value.name.trim()) {
    ElMessage.warning('请填写租户编码与名称');
    return;
  }
  submitting.value = true;
  try {
    await createTenantApi({ ...form.value });
    ElMessage.success('租户已创建');
    dialog.value = false;
    await load();
    emit('changed');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
};

const pick = (row: TenantItem) => {
  emit('pick-quota', row);
};

const toggle = async (row: TenantItem) => {
  const next = row.status === 'active' ? 'suspended' : 'active';
  await ElMessageBox.confirm(
    `确认将租户「${row.code}」置为${next === 'active' ? '正常' : '停服'}吗？`,
    '危险操作',
  );
  try {
    await setTenantStatusApi({ code: row.code, status: next });
    ElMessage.success('租户状态已更新');
    await load();
    emit('changed');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  }
};

onMounted(() => {
  load();
});

defineExpose({ reload: load });
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.kw {
  width: 220px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
