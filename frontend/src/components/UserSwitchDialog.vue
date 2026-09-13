<template>
  <el-dialog :model-value="modelValue" title="切换用户" width="640px" @close="close">
    <div class="toolbar">
      <AiInput v-model="keyword" placeholder="搜用户名" class="kw" @keyup.enter="reload" />
      <AiButton @click="reload">查询</AiButton>
      <span class="hint">仅本租户用户；代入后记审计且当前登录态被替换</span>
    </div>
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column label="角色" min-width="200">
        <template #default="s">{{ (s.row.roles ?? []).join(',') }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="110">
        <template #default="s">
          <AiButton link :disabled="s.row.username === currentName" @click="doSwitch(s.row)">
            {{ s.row.username === currentName ? '当前' : '切换' }}
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
  </el-dialog>
</template>

<script setup lang="ts">
// 管理员代入弹窗：本租户用户分页列表（默认 20）+ confirm 后免密代入（对齐页面设计 §2 顶栏）
// 列表只读展示，换 token 与跳转由调用方经 user store 完成；失败 ElMessage 提示。
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, ref, watch } from 'vue';
import { listAdminUsersApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { useUserStore } from '@/stores/user';
import type { AdminUserItem } from '@/types/admin';

const props = defineProps({ modelValue: { type: Boolean, default: false } });
const emit = defineEmits(['update:modelValue', 'switched']);

const userStore = useUserStore();
const currentName = computed(() => userStore.user?.name ?? '');
const tenant = computed(() => userStore.user?.tenant ?? '');

const rows = ref<AdminUserItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const loading = ref(false);
const switching = ref(false);

const close = () => {
  emit('update:modelValue', false);
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listAdminUsersApi({
      tenant: tenant.value,
      keyword: keyword.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载用户失败');
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

const doSwitch = async (row: AdminUserItem) => {
  if (switching.value) {
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确认切换到用户「${row.username}」吗？当前登录态将被替换。`,
      '切换用户',
    );
  } catch {
    return; // 用户取消
  }
  switching.value = true;
  try {
    await userStore.switchUser(row.username);
    ElMessage.success(`已切换到用户${row.username}`);
    close();
    emit('switched', row.username);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '切换失败');
  } finally {
    switching.value = false;
  }
};

watch(
  () => props.modelValue,
  opened => {
    if (opened) {
      reload();
    }
  },
);
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
  width: 200px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
