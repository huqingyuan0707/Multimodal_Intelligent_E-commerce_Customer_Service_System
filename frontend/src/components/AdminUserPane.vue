<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
      <AiInput v-model="keyword" placeholder="搜用户名" class="kw" />
      <AiInput v-model="status" placeholder="状态 active/frozen" class="kw-sm" />
      <AiButton @click="reload">查询</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="tenant" label="租户" min-width="130" />
      <el-table-column prop="username" label="用户名" min-width="130" />
      <el-table-column label="角色" min-width="180">
        <template #default="s">{{ (s.row.roles ?? []).join(',') }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="userStatusTagOf(s.row.status)" size="small">{{
            s.row.status_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="open(s.row)">改角色</AiButton>
          <AiButton v-permission="['admin']" link @click="toggleFrozen(s.row)">
            {{ s.row.status === 'frozen' ? '解冻' : '离职冻结' }}
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
    <el-dialog v-model="dialog" title="改用户角色" width="440px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户">{{ form.username }}</el-form-item>
        <el-form-item label="角色"
          ><AiInput v-model="form.roles" placeholder="如 cs,admin"
        /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">保存</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 用户角色窗格：全局用户分页（默认 20）+ 改角色 + 离职冻结（拒登但保留行，可回溯到人）
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { listAdminUsersApi, setUserFrozenApi, updateUserRolesApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { userStatusTagOf } from '@/types/admin';
import type { AdminUserItem } from '@/types/admin';

const rows = ref<AdminUserItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const tenant = ref('');
const keyword = ref('');
const status = ref('');
const loading = ref(false);
const submitting = ref(false);
const dialog = ref(false);
const form = ref({ id: '', username: '', roles: '' });

const load = async () => {
  loading.value = true;
  try {
    const res = await listAdminUsersApi({
      tenant: tenant.value.trim(),
      keyword: keyword.value.trim(),
      status: status.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
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

const open = (row: AdminUserItem) => {
  form.value = { id: row.id, username: row.username, roles: row.roles.join(',') };
  dialog.value = true;
};

const submit = async () => {
  if (!form.value.roles.trim()) {
    ElMessage.warning('角色不能为空');
    return;
  }
  await ElMessageBox.confirm(`确认修改用户「${form.value.username}」的角色吗？`, '提示');
  submitting.value = true;
  try {
    await updateUserRolesApi({ userId: form.value.id, roles: form.value.roles });
    ElMessage.success('用户角色已更新');
    dialog.value = false;
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  } finally {
    submitting.value = false;
  }
};

const toggleFrozen = async (row: AdminUserItem) => {
  const frozen = row.status !== 'frozen';
  // 冻结/解冻直接决定「这个人能不能登录」，与配额同级：不可逆到人 → 双重确认
  await ElMessageBox.confirm(
    `确认${frozen ? '冻结' : '解冻'}「${row.username}」吗？${frozen ? '冻结后该账号无法登录。' : ''}`,
    '危险操作',
  );
  if (frozen) {
    await ElMessageBox.confirm('离职冻结立即生效，请再次确认', '二次确认');
  }
  try {
    await setUserFrozenApi({ userId: row.id, frozen });
    ElMessage.success(frozen ? '账号已冻结' : '账号已解冻');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  }
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

.kw-sm {
  width: 160px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
