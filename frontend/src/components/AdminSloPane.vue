<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
      <AiButton @click="reload">查询</AiButton>
      <AiButton v-permission="['admin']" type="primary" @click="openCreate">新增规则</AiButton>
    </div>
    <!-- 值的来源层级必须展示：规则按租户存，但实时值是进程级聚合（含全部租户） -->
    <el-alert v-if="scopeNote" :title="scopeNote" type="info" :closable="false" show-icon />
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column label="指标" min-width="170">
        <template #default="s">{{ s.row.metric_label }}</template>
      </el-table-column>
      <el-table-column label="目标" min-width="150">
        <template #default="s">
          {{ sloOperatorLabelOf(s.row.operator) }} {{ formatSloValue(s.row.threshold, s.row.unit) }}
        </template>
      </el-table-column>
      <el-table-column label="当前值" min-width="120">
        <template #default="s">
          <span v-if="s.row.no_data" class="muted">无数据</span>
          <span v-else>{{ formatSloValue(s.row.current, s.row.unit) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="结论" width="110">
        <template #default="s">
          <el-tag v-if="!s.row.enabled" type="info" size="small">已停用</el-tag>
          <el-tag v-else-if="s.row.no_data" type="warning" size="small">未测过</el-tag>
          <el-tag v-else :type="s.row.breach ? 'danger' : 'success'" size="small">
            {{ s.row.breach ? '已超标' : '达标' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="tenant" label="租户" min-width="120" />
      <el-table-column label="操作" width="140">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="edit(s.row)">改口径</AiButton>
          <AiButton v-permission="['admin']" link @click="toggle(s.row)">
            {{ s.row.enabled ? '停用' : '启用' }}
          </AiButton>
          <AiButton v-permission="['admin']" link @click="remove(s.row)">删除</AiButton>
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

    <el-dialog v-model="dialog" title="SLO 规则" width="480px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="租户"><AiInput v-model="form.tenant" /></el-form-item>
        <el-form-item label="指标">
          <el-select v-model="form.metric" class="kw-full" @change="onMetricChange">
            <el-option
              v-for="item in metrics"
              :key="item.metric"
              :label="`${item.label}（当前 ${formatSloValue(item.current, item.unit)}）`"
              :value="item.metric"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="form.operator" class="kw-full">
            <el-option label="不低于（目标下限）" value="gte" />
            <el-option label="不高于（目标上限）" value="lte" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值">
          <AiInput v-model="form.threshold" placeholder="比率写 0.95，秒/次写数字" />
        </el-form-item>
        <el-form-item label="备注"><AiInput v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">保存</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// SLO 窗格（FR-8「SLO 告警」）：规则存阈值口径，实时值现取（规则表不存结论）。
// 值来自进程级聚合 → 顶部固定展示 scope_note；无数据标「未测过」而不是显示 0%。
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import {
  deleteSloRuleApi,
  getSloMetricsApi,
  listSloRulesApi,
  saveSloRuleApi,
  setSloRuleEnabledApi,
} from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { formatSloValue, sloOperatorLabelOf } from '@/types/admin';
import type { SloMetricItem, SloRuleItem } from '@/types/admin';

const rows = ref<SloRuleItem[]>([]);
const metrics = ref<SloMetricItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const tenant = ref('');
const scopeNote = ref('');
const loading = ref(false);
const submitting = ref(false);
const dialog = ref(false);
const form = ref({
  tenant: '',
  metric: 'handoff_answer_rate',
  operator: 'gte',
  threshold: '0.95',
  note: '',
});

const loadMetrics = async () => {
  try {
    const res = await getSloMetricsApi();
    metrics.value = res.items;
    scopeNote.value = res.scope_note;
  } catch {
    metrics.value = [];
    scopeNote.value = '';
  }
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listSloRulesApi({
      tenant: tenant.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    scopeNote.value = res.scope_note;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载 SLO 规则失败');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
  loadMetrics();
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

const onMetricChange = (metric: string) => {
  // 选指标时带出建议方向与阈值，减少手填错口径的概率（可改）
  const meta = metrics.value.find(item => item.metric === metric);
  if (meta) {
    form.value.operator = meta.operator;
    form.value.threshold = String(meta.threshold);
  }
};

const openCreate = () => {
  form.value = {
    tenant: tenant.value.trim(),
    metric: metrics.value[0]?.metric ?? 'handoff_answer_rate',
    operator: metrics.value[0]?.operator ?? 'gte',
    threshold: String(metrics.value[0]?.threshold ?? 0.95),
    note: '',
  };
  dialog.value = true;
};

const edit = (row: SloRuleItem) => {
  form.value = {
    tenant: row.tenant,
    metric: row.metric,
    operator: row.operator,
    threshold: String(row.threshold),
    note: row.note,
  };
  dialog.value = true;
};

const submit = async () => {
  if (!form.value.tenant.trim()) {
    ElMessage.warning('请填写租户编码');
    return;
  }
  if (!form.value.threshold.trim() || Number.isNaN(Number(form.value.threshold))) {
    ElMessage.warning('阈值必须是数字');
    return;
  }
  submitting.value = true;
  try {
    await saveSloRuleApi({
      tenant: form.value.tenant.trim(),
      metric: form.value.metric,
      operator: form.value.operator,
      threshold: Number(form.value.threshold),
      note: form.value.note.trim(),
    });
    ElMessage.success('规则已保存');
    dialog.value = false;
    await reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败');
  } finally {
    submitting.value = false;
  }
};

const toggle = async (row: SloRuleItem) => {
  try {
    await setSloRuleEnabledApi({ ruleId: row.id, enabled: !row.enabled });
    ElMessage.success('规则状态已更新');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  }
};

const remove = async (row: SloRuleItem) => {
  await ElMessageBox.confirm(`确认删除「${row.metric_label}」告警规则吗？`, '提示');
  try {
    await deleteSloRuleApi({ ruleId: row.id });
    ElMessage.success('规则已删除');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败');
  }
};

onMounted(() => {
  load();
  loadMetrics();
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

.kw-full {
  width: 100%;
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
