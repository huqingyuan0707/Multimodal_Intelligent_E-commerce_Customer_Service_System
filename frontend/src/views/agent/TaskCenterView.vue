<template>
  <div class="page">
    <p class="hint">长任务（批量导入 / reindex / 大图检测）异步执行 · 短任务不进此页</p>
    <el-card class="create-card" header="新建任务">
      <el-form :model="form" label-width="90px" @submit.prevent>
        <el-form-item label="任务类型">
          <el-select v-model="form.type" placeholder="选择任务类型">
            <el-option label="知识重建索引" value="reindex" />
            <el-option label="批量导入" value="import" />
            <el-option label="离线评估" value="eval" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.type === 'reindex'" label="范围">
          <el-select v-model="form.scope" placeholder="重建范围">
            <el-option label="全量" value="all" />
            <el-option label="指定渠道" value="channel" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.type === 'reindex' && form.scope === 'channel'" label="渠道">
          <AiInput v-model="form.channel" placeholder="渠道标识，如 miniapp" clearable />
        </el-form-item>
        <el-form-item>
          <AiButton type="primary" :loading="creating" @click="create">提交任务</AiButton>
          <span class="hint">超 30s 自动转异步，可离开本页</span>
        </el-form-item>
      </el-form>
    </el-card>
    <div class="toolbar">
      <el-select v-model="status" placeholder="状态筛选" style="width: 140px" @change="onFilter">
        <el-option label="全部" value="" />
        <el-option label="待执行" value="pending" />
        <el-option label="执行中" value="running" />
        <el-option label="已完成" value="done" />
        <el-option label="失败" value="error" />
      </el-select>
      <AiButton @click="reload">刷新</AiButton>
    </div>
    <el-empty v-if="!tasks.length && !loading" description="暂无任务，可在上方新建" />
    <el-table v-loading="loading" :data="tasks" style="width: 100%" :row-class-name="rowTone">
      <el-table-column prop="task_id" label="任务ID" min-width="180" />
      <el-table-column label="类型" width="140">
        <template #default="{ row }">{{ typeLabel(row.type) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusTag(row)">{{ statusLabel(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" min-width="160">
        <template #default="{ row }">
          <el-progress :percentage="Math.round((row.progress ?? 0) * 100)" />
        </template>
      </el-table-column>
      <el-table-column label="结果/错误" min-width="200">
        <template #default="{ row }">
          <span v-if="row.status === 'error'" class="err">{{ errText(row) }}</span>
          <span v-else class="hint">{{ resultText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <AiButton link size="small" @click="openLog(row)">查看日志</AiButton>
          <AiButton v-if="row.status === 'done'" link size="small" @click="download(row)">
            下载结果
          </AiButton>
          <AiButton v-if="row.status === 'error'" link size="small" type="danger" @click="retry(row)">
            重试
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
      @size-change="onSize"
      @current-change="onPage"
    />
    <el-dialog v-model="logVisible" title="任务详情（服务端返回原样）" width="640px">
      <pre class="content">{{ logText }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 任务中心：服务端真实列表（本人维度倒序，状态筛选+分页）+ 新建 + 活跃任务3s轮询
// 对齐 API 规范 §4.5、页面设计 §3.3、画板 任务中心-/tasks；取消接口后端暂无，不提供取消按钮
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, onUnmounted, ref } from 'vue';
import { createTaskApi, getTaskApi, listTasksApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { TaskItem, TaskStatus } from '@/types/task';
import { TASK_STATUS_TAG, TASK_TYPE_TAG } from '@/types/task';

type TaskType = keyof typeof TASK_TYPE_TAG;

const form = ref({ type: 'reindex', scope: 'all', channel: '' });
const tasks = ref<TaskItem[]>([]);
const status = ref('');
const page = ref(1);
const size = ref(20);
const total = ref(0);
const loading = ref(false);
const creating = ref(false);
const logVisible = ref(false);
const logText = ref('');
let timer: ReturnType<typeof setInterval> | null = null;
// 状态变更闪光：轮询发现 status 变化的行高亮一次（目的性动效，非装饰）
const flashIds = ref<string[]>([]);
let flashTimer = 0;

const markFlash = (id: string) => {
  if (!flashIds.value.includes(id)) {
    flashIds.value = [...flashIds.value, id];
  }
  window.clearTimeout(flashTimer);
  flashTimer = window.setTimeout(() => {
    flashIds.value = [];
  }, 900);
};

const statusType = (s: TaskStatus) => {
  const map = {
    pending: 'info',
    running: 'warning',
    done: 'success',
    error: 'danger',
  } as const;
  return map[s];
};

// el-table 行在模板中为隐式 any，经此收窄后再索引映射表（过 strict）
const statusLabel = (row: { status: TaskStatus }) => TASK_STATUS_TAG[row.status];

// 任务类型中文化，未知类型回退原值展示（不丢信息）
const typeLabel = (t: string) => (t in TASK_TYPE_TAG ? TASK_TYPE_TAG[t as TaskType] : t);

const statusTag = (row: { status: TaskStatus }) => statusType(row.status);

const rowTone = (data: { row: TaskItem }) => {
  const tones: string[] = [];
  if (data.row.status === 'error') tones.push('row-error');
  if (flashIds.value.includes(data.row.task_id)) tones.push('row-flash');
  return tones.join(' ');
};

const errText = (row: TaskItem) => {
  const e = row.error;
  if (typeof e === 'string') return e.slice(0, 80);
  if (e && typeof e === 'object') {
    const m = (e as { msg?: unknown }).msg ?? (e as { message?: unknown }).message;
    return String(m ?? JSON.stringify(e)).slice(0, 80);
  }
  return '执行失败，可重试';
};

const resultText = (row: TaskItem) => {
  if (row.status !== 'done') return '—';
  const r = row.result;
  if (r && typeof r === 'object') {
    const docs = (r as { docs?: unknown }).docs;
    const chunks = (r as { chunks?: unknown }).chunks;
    if (docs !== undefined || chunks !== undefined) return `文档 ${String(docs ?? '—')} · 分块 ${String(chunks ?? '—')}`;
  }
  return '已完成，可下载结果';
};

const normalizeStatus = (s: string) =>
  s === 'running' || s === 'done' || s === 'error' ? s : 'pending';

const load = async () => {
  loading.value = true;
  try {
    const res = await listTasksApi({ page: page.value, size: size.value, status: status.value });
    const items: TaskItem[] = Array.isArray(res) ? res : (res.items ?? []);
    tasks.value = items;
    // 后端暂只返数组无 total：满页则 +1 探针保证“下一页”可点，空页即到头
    total.value = (page.value - 1) * size.value + items.length + (items.length === size.value ? 1 : 0);
  } catch (e) {
    tasks.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '任务列表加载失败，请点刷新重试');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
};

const onFilter = () => {
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

const poll = async () => {
  const actives = tasks.value.filter(t => t.status === 'pending' || t.status === 'running');
  if (!actives.length) {
    return;
  }
  await Promise.all(
    actives.map(async t => {
      try {
        const r = await getTaskApi({ taskId: t.task_id });
        const next = normalizeStatus(String(r.status ?? t.status));
        if (next !== t.status) {
          t.status = next;
          markFlash(t.task_id);
        }
        t.progress = typeof r.progress === 'number' ? r.progress : t.progress;
        if ('result' in r) t.result = r.result;
        if ('error' in r) t.error = r.error;
      } catch {
        t.status = 'error';
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
  if (form.value.type === 'reindex' && form.value.scope === 'channel' && !form.value.channel.trim()) {
    ElMessage.warning('已选指定渠道，请填写渠道标识');
    return;
  }
  creating.value = true;
  try {
    const payload =
      form.value.type === 'reindex'
        ? { scope: form.value.scope, channel: form.value.channel.trim() || undefined }
        : {};
    const r = await createTaskApi({ type: form.value.type, payload });
    ElMessage.success(`任务已提交（${String(r.task_id ?? '')}），可在列表观察进度（3s 刷新）`);
    if (r.task_id) markFlash(String(r.task_id));
    ensureTimer();
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败，请稍后重试');
  } finally {
    creating.value = false;
  }
};

const openLog = async (row: TaskItem) => {
  try {
    const r = await getTaskApi({ taskId: row.task_id });
    logText.value = JSON.stringify({ result: r.result ?? null, error: r.error ?? null }, null, 2);
  } catch {
    logText.value = JSON.stringify({ result: row.result ?? null, error: row.error ?? null }, null, 2);
  }
  logVisible.value = true;
};

const download = async (row: TaskItem) => {
  try {
    const r = await getTaskApi({ taskId: row.task_id });
    const blob = new Blob([JSON.stringify(r.result ?? {}, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${row.task_id}-result.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下载失败，请稍后重试');
  }
};

const retry = async (row: TaskItem) => {
  await ElMessageBox.confirm('重试将按同类型新建任务并覆盖上次产物，确认吗？', '提示');
  try {
    await createTaskApi({ type: row.type });
    ElMessage.success('已按同类型重新提交，请在列表观察进度');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '重试失败，请稍后重试');
  }
};

onMounted(() => {
  load();
  ensureTimer();
});

onUnmounted(() => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
  window.clearTimeout(flashTimer);
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.create-card {
  max-width: 560px;
}

.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.err {
  font-size: 12px;
  color: var(--reai-notice);
}

.content {
  max-height: 420px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.page :deep(.row-error) {
  background: var(--reai-notice-soft);
}

/* 目的性动效：状态变更行闪光（仅提示变化，无装饰性动画） */

@keyframes row-flash-in {
  0% {
    background: var(--reai-primary-soft);
  }

  100% {
    background: transparent;
  }
}

.page :deep(.row-flash) {
  animation: row-flash-in 0.9s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .page :deep(.row-flash) {
    animation: none;
  }
}
</style>
