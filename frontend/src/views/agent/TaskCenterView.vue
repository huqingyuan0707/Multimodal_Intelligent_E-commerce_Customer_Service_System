<template>
  <div class="page">
    <h2>任务中心</h2>
    <el-card class="create-card" header="新建任务">
      <el-form :model="form" label-width="90px" @submit.prevent>
        <el-form-item label="任务类型">
          <el-select v-model="form.type" placeholder="选择类型">
            <el-option label="知识重建索引" value="reindex" />
            <el-option label="批量导入" value="import" />
            <el-option label="离线评估" value="eval" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <AiButton type="primary" :loading="creating" @click="create">提交</AiButton>
        </el-form-item>
      </el-form>
    </el-card>
    <el-empty v-if="!tasks.length" description="暂无任务（后端暂无列表接口，仅展示本机会话内创建的任务）" />
    <el-table v-else :data="tasks" style="width: 100%">
      <el-table-column prop="task_id" label="任务ID" min-width="180" />
      <el-table-column prop="type" label="类型" width="140" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusTag(row)">{{ statusLabel(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" min-width="160">
        <template #default="{ row }">
          <el-progress :percentage="Math.round(row.progress * 100)" />
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
// 任务中心：本地任务盒 + 单查轮询（后端暂无 GET /tasks 列表接口，见缺失项）
// 长任务 >30s 转异步 + 轮询；SSE progress/complete/error 待后端补后接入
import { ElMessage } from 'element-plus';
import { onUnmounted, ref } from 'vue';
import { createTaskApi, getTaskApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { TaskItem, TaskStatus } from '@/types/task';
import { TASK_STATUS_TAG } from '@/types/task';

const form = ref({ type: 'reindex' });
const tasks = ref<TaskItem[]>([]);
const creating = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

const statusType = (s: TaskStatus) => {
  const map = {
    pending: 'info',
    running: 'warning',
    done: 'success',
    error: 'danger',
  } as const;
  return map[s];
};

const normalizeStatus = (s: string) =>
  s === 'running' || s === 'done' || s === 'error' ? s : 'pending';

// el-table 行在模板中为隐式 any，经此收窄后再索引映射表（过 strict）
const statusLabel = (row: { status: TaskStatus }) => TASK_STATUS_TAG[row.status];

const statusTag = (row: { status: TaskStatus }) => statusType(row.status);

const poll = async () => {
  const actives = tasks.value.filter(t => t.status === 'pending' || t.status === 'running');
  if (!actives.length) {
    return;
  }
  await Promise.all(
    actives.map(async t => {
      try {
        const r = await getTaskApi({ taskId: t.task_id });
        t.status = normalizeStatus(r.status);
        t.progress = r.progress ?? t.progress;
      } catch (e) {
        t.status = 'error';
        ElMessage.error(e instanceof Error ? e.message : '查询任务失败');
      }
    }),
  );
};

const ensureTimer = () => {
  if (timer) {
    return;
  }
  timer = setInterval(() => {
    poll();
  }, 3000);
};

const create = async () => {
  creating.value = true;
  try {
    const r = await createTaskApi({ type: form.value.type });
    // 后端 stub 暂返空 task_id：本地生成占位 id，保证列表可用
    const id = r.task_id || `t-${Date.now()}`;
    tasks.value = [
      {
        task_id: id,
        type: form.value.type,
        status: 'pending',
        progress: 0,
        created_at: new Date().toLocaleString(),
      },
      ...tasks.value,
    ];
    ElMessage.success('任务已提交，3s 轮询进度');
    ensureTimer();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建任务失败');
  } finally {
    creating.value = false;
  }
};

onUnmounted(() => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.create-card {
  max-width: 560px;
}
</style>
