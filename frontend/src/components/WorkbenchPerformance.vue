<template>
  <el-dialog
    :model-value="modelValue"
    title="坐席绩效（已解决会话质检口径）"
    width="720px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="meta">
      质检通过线 {{ data?.pass_score ?? '-' }} 分 · 自动评分{{
        data?.auto_enabled ? '已开启' : '已关闭'
      }}
    </p>
    <el-table v-loading="loading" :data="rows" size="small" empty-text="暂无已解决会话">
      <el-table-column prop="assignee" label="坐席" min-width="90" />
      <el-table-column prop="resolved" label="解决会话" width="90" />
      <el-table-column prop="scored" label="已评分" width="80" />
      <el-table-column label="质检均分" width="90">
        <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="通过率" width="90">
        <template #default="{ row }">
          {{ row.pass_rate == null ? '—' : `${Math.round(row.pass_rate * 100)}%` }}
        </template>
      </el-table-column>
      <el-table-column prop="manual_reviews" label="人工复核" width="80" />
      <el-table-column prop="unscored" label="待评分" width="80" />
    </el-table>
  </el-dialog>
</template>

<script setup lang="ts">
// 坐席绩效弹窗（C 步收官）：按 assignee 聚合已解决会话的质检口径
// 打开时拉 /workbench/performance，失败置空表 + 中文提示；对齐 API 规范 §4.11
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { performanceWorkbenchApi } from '@/api';
import type { WorkbenchAgentPerf, WorkbenchPerformance } from '@/api';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits(['update:modelValue']);

const data = ref<WorkbenchPerformance | null>(null);
const loading = ref(false);
const rows = computed<WorkbenchAgentPerf[]>(() => data.value?.agents ?? []);

const load = async () => {
  loading.value = true;
  try {
    data.value = (await performanceWorkbenchApi()) as WorkbenchPerformance;
  } catch (e) {
    data.value = null;
    ElMessage.error(e instanceof Error ? `加载绩效失败：${e.message}` : '加载绩效失败');
  } finally {
    loading.value = false;
  }
};

// 每次打开都重拉（首次 mount 即 modelValue=true 时 el-dialog 不发 open 事件，watch 更可靠）
watch(
  () => props.modelValue,
  value => {
    if (value) load();
  },
  { immediate: true },
);
</script>

<style scoped>
.meta {
  margin: 0 0 12px;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
