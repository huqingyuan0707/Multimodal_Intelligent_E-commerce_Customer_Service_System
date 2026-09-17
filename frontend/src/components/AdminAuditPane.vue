<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
      <AiInput v-model="keyword" placeholder="搜操作人/目标" class="kw" />
      <AiButton @click="reload">查询</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column prop="tenant" label="租户" width="130" />
      <el-table-column prop="actor" label="操作人" width="110" />
      <el-table-column prop="action" label="动作" min-width="150" />
      <el-table-column prop="target" label="目标" min-width="150" />
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
  </div>
</template>

<script setup lang="ts">
// 审计窗格：只读倒序分页（默认 20），后端不可用置空 + 中文提示
import { ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { listAuditsApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AuditItem } from '@/types/admin';

const rows = ref<AuditItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const tenant = ref('');
const keyword = ref('');
const loading = ref(false);

const load = async () => {
  loading.value = true;
  try {
    const res = await listAuditsApi({
      tenant: tenant.value.trim(),
      keyword: keyword.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? `加载审计失败：${e.message}` : '加载审计失败');
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

onMounted(() => {
  load();
});
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
