<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="排班" name="shift">
      <div class="toolbar">
        <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
        <AiInput v-model="username" placeholder="坐席用户名" class="kw-sm" />
        <AiInput v-model="workDate" placeholder="日期 YYYY-MM-DD" class="kw-sm" />
        <AiButton @click="reloadShifts">查询</AiButton>
        <AiButton v-permission="['admin']" type="primary" @click="openCreate">登记排班</AiButton>
      </div>
      <el-table v-loading="shiftLoading" :data="shifts" style="width: 100%">
        <el-table-column prop="work_date" label="日期" width="120" />
        <el-table-column prop="username" label="坐席" min-width="130" />
        <el-table-column label="时段" min-width="140">
          <template #default="s">{{ s.row.start_time }} - {{ s.row.end_time }}</template>
        </el-table-column>
        <el-table-column label="技能组" width="120">
          <template #default="s">
            <el-tag size="small">{{ s.row.skill_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tenant" label="租户" min-width="120" />
        <el-table-column label="操作" width="90">
          <template #default="s">
            <AiButton v-permission="['admin']" link @click="removeShift(s.row)">删除</AiButton>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          :current-page="shiftPage"
          :page-size="shiftSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="shiftTotal"
          layout="sizes, prev, pager, next, total"
          @current-change="onShiftPage"
          @size-change="onShiftSize"
        />
      </div>
    </el-tab-pane>

    <el-tab-pane label="绩效到人" name="perf">
      <div class="toolbar">
        <AiInput v-model="perfTenant" placeholder="租户编码（必填）" class="kw" />
        <AiInput v-model="perfUser" placeholder="坐席用户名（空=全部）" class="kw-sm" />
        <AiButton @click="reloadPerf">查询</AiButton>
      </div>
      <p class="hint">{{ perf.privacy_note }}</p>
      <p class="hint">{{ perf.scope_note }}</p>
      <el-table v-loading="perfLoading" :data="perf.items" style="width: 100%">
        <el-table-column prop="username" label="坐席" min-width="130" />
        <el-table-column prop="handled" label="接手会话" width="110" />
        <el-table-column prop="resolved" label="已解决" width="100" />
        <el-table-column label="解决率" width="110">
          <template #default="s">{{ formatRate(s.row.resolve_rate) }}</template>
        </el-table-column>
        <el-table-column label="质检均分" width="120">
          <template #default="s">
            <span v-if="s.row.no_score" class="muted">未评分</span>
            <span v-else>{{ s.row.avg_score }}（{{ s.row.scored_sessions }} 条）</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          :current-page="perfPage"
          :page-size="perfSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="perf.total"
          layout="sizes, prev, pager, next, total"
          @current-change="onPerfPage"
          @size-change="onPerfSize"
        />
      </div>
    </el-tab-pane>
  </el-tabs>

  <el-dialog v-model="dialog" title="登记排班" width="480px">
    <el-form :model="form" label-width="90px">
      <el-form-item label="租户"><AiInput v-model="form.tenant" /></el-form-item>
      <el-form-item label="坐席"><AiInput v-model="form.username" /></el-form-item>
      <el-form-item label="日期"
        ><AiInput v-model="form.work_date" placeholder="YYYY-MM-DD"
      /></el-form-item>
      <el-form-item label="开始"
        ><AiInput v-model="form.start_time" placeholder="09:00"
      /></el-form-item>
      <el-form-item label="结束"
        ><AiInput v-model="form.end_time" placeholder="18:00"
      /></el-form-item>
      <el-form-item label="技能组">
        <el-select v-model="form.skill" class="kw-full">
          <el-option v-for="s in skills" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="备注"><AiInput v-model="form.note" /></el-form-item>
    </el-form>
    <template #footer>
      <AiButton @click="dialog = false">取消</AiButton>
      <AiButton type="primary" :loading="submitting" @click="submit">保存</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 组织窗格（FR-12.4 + 页面设计 §3.19）：排班（技能组取值与队列路由同源）+ 绩效到人。
// 绩效为坐席维度聚合、不含买家标识（privacy_note 由后端下发并原样展示，不自己另写口径）。
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { createShiftApi, deleteShiftApi, getPerformanceApi, listShiftsApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { formatRate } from '@/types/admin';
import type { PerformanceReport, ShiftItem, SkillOption } from '@/types/admin';

const tab = ref('shift');
const tenant = ref('');
const username = ref('');
const workDate = ref('');
const shifts = ref<ShiftItem[]>([]);
const skills = ref<SkillOption[]>([]);
const shiftTotal = ref(0);
const shiftPage = ref(1);
const shiftSize = ref(20);
const shiftLoading = ref(false);
const submitting = ref(false);
const dialog = ref(false);
const form = ref({
  tenant: '',
  username: '',
  work_date: '',
  start_time: '09:00',
  end_time: '18:00',
  skill: 'general',
  note: '',
});

const perfTenant = ref('');
const perfUser = ref('');
const perfPage = ref(1);
const perfSize = ref(20);
const perfLoading = ref(false);
const perf = ref<PerformanceReport>({
  items: [],
  total: 0,
  page: 1,
  size: 20,
  privacy_note: '',
  scope_note: '',
});

const loadShifts = async () => {
  shiftLoading.value = true;
  try {
    const res = await listShiftsApi({
      tenant: tenant.value.trim(),
      username: username.value.trim(),
      work_date: workDate.value.trim(),
      page: shiftPage.value,
      size: shiftSize.value,
    });
    shifts.value = res.items;
    shiftTotal.value = res.total;
    skills.value = res.skills;
  } catch (e) {
    shifts.value = [];
    shiftTotal.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载排班失败');
  } finally {
    shiftLoading.value = false;
  }
};

const reloadShifts = () => {
  shiftPage.value = 1;
  loadShifts();
};

const onShiftPage = (p: number) => {
  shiftPage.value = p;
  loadShifts();
};

const onShiftSize = (s: number) => {
  shiftSize.value = s;
  shiftPage.value = 1;
  loadShifts();
};

const loadPerf = async () => {
  if (!perfTenant.value.trim()) {
    ElMessage.warning('请先填写租户编码');
    return;
  }
  perfLoading.value = true;
  try {
    perf.value = await getPerformanceApi({
      tenant: perfTenant.value.trim(),
      username: perfUser.value.trim(),
      page: perfPage.value,
      size: perfSize.value,
    });
  } catch (e) {
    perf.value = { ...perf.value, items: [], total: 0 };
    ElMessage.error(e instanceof Error ? e.message : '加载绩效失败');
  } finally {
    perfLoading.value = false;
  }
};

const reloadPerf = () => {
  perfPage.value = 1;
  loadPerf();
};

const onPerfPage = (p: number) => {
  perfPage.value = p;
  loadPerf();
};

const onPerfSize = (s: number) => {
  perfSize.value = s;
  perfPage.value = 1;
  loadPerf();
};

const openCreate = () => {
  form.value = {
    tenant: tenant.value.trim(),
    username: '',
    work_date: new Date().toISOString().slice(0, 10),
    start_time: '09:00',
    end_time: '18:00',
    skill: skills.value[0]?.value ?? 'general',
    note: '',
  };
  dialog.value = true;
};

const submit = async () => {
  if (!form.value.tenant.trim() || !form.value.username.trim()) {
    ElMessage.warning('请填写租户与坐席');
    return;
  }
  submitting.value = true;
  try {
    await createShiftApi({ ...form.value });
    ElMessage.success('排班已登记');
    dialog.value = false;
    await loadShifts();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败');
  } finally {
    submitting.value = false;
  }
};

const removeShift = async (row: ShiftItem) => {
  await ElMessageBox.confirm(`确认删除 ${row.work_date} ${row.username} 的排班吗？`, '提示');
  try {
    await deleteShiftApi({ shiftId: row.id });
    ElMessage.success('排班已删除');
    await loadShifts();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败');
  }
};

onMounted(() => {
  loadShifts();
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
  width: 200px;
}

.kw-sm {
  width: 150px;
}

.kw-full {
  width: 100%;
}

.hint {
  color: var(--reai-text-muted);
  font-size: 12px;
  margin: 0 0 6px;
}

.muted {
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
