<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="goldSet" placeholder="黄金集（如 default-200）" clearable />
      <el-select v-model="evalLimit" placeholder="采样数" style="width: 130px">
        <el-option :value="20" label="采样 20" />
        <el-option :value="50" label="采样 50" />
        <el-option :value="100" label="采样 100" />
        <el-option :value="200" label="采样 200" />
      </el-select>
      <AiButton
        v-permission="['ops', 'admin']"
        type="primary"
        :loading="running"
        @click="submitRun"
      >
        一键跑
      </AiButton>
    </div>
    <el-alert
      v-if="current && !current.pass"
      type="error"
      show-icon
      title="不达标禁发布：未达棘轮基线（grounded≥0.92 且幻觉率≤0.03）时禁止发布全量版本"
    />
    <el-descriptions :column="3" border>
      <el-descriptions-item label="grounded">{{ display.grounded }}</el-descriptions-item>
      <el-descriptions-item label="幻觉率">{{ display.hallucination }}</el-descriptions-item>
      <el-descriptions-item label="结论">{{ display.verdict }}</el-descriptions-item>
      <el-descriptions-item label="guard 分布">{{ display.guardDist }}</el-descriptions-item>
      <el-descriptions-item label="耗时">{{ display.elapsed }}</el-descriptions-item>
      <el-descriptions-item label="采样">{{ display.sample }}</el-descriptions-item>
    </el-descriptions>
    <el-table
      v-if="current && current.score.misses.length"
      :data="current.score.misses"
      style="width: 100%; margin-top: 8px"
    >
      <el-table-column prop="id" label="用例" width="100" />
      <el-table-column prop="scene" label="场景" width="120" />
      <el-table-column prop="query" label="问题" min-width="200" />
    </el-table>
    <div class="toolbar" style="margin-top: 12px">
      <span class="hint">历史评测（点击查看详情）</span>
    </div>
    <el-table v-loading="loading" :data="runs" style="width: 100%">
      <el-table-column prop="name" label="黄金集" width="140" />
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="evalTag(s.row.status)" size="small">
            {{ EVAL_TAG[s.row.status] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="结论" width="120">
        <template #default="s">{{ s.row.pass ? '达标' : '未达标' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="s">
          <AiButton v-permission="['ops', 'admin']" link @click="emit('view', s.row.id)">
            查看
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      :current-page="page"
      :page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next, total"
      @size-change="emit('size-change', $event)"
      @current-change="emit('page-change', $event)"
    />
  </div>
</template>

<script setup lang="ts">
// Studio 评测窗格（一键跑 + 双档 verdict + 分布/misses + 历史，对齐页面设计 §3.6）
// 纯展示 + 跑参本地态；建 run 与轮询上抛给 StudioView（唯一调用 composable 处）
import { computed, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { EvalRun } from '@/types/agent';

type EvalStatus = keyof typeof EVAL_TAG;

const props = defineProps<{
  runs: EvalRun[];
  total: number;
  page: number;
  size: number;
  current: EvalRun | null;
  loading: boolean;
  running: boolean;
}>();

const emit = defineEmits(['page-change', 'size-change', 'run', 'view']);

const EVAL_TAG = {
  pending: '等待中',
  running: '运行中',
  done: '已完成',
  failed: '失败',
} as const;

const goldSet = ref('default-200');
const evalLimit = ref(50);

const evalTag = (s: EvalStatus) => {
  if (s === 'done') return 'success';
  if (s === 'running') return 'primary';
  if (s === 'failed') return 'danger';
  return 'info';
};

// 展示文案三态：无 run 显示占位、跑分中显示进度、完成显示双档结论（红条由模板 v-if 驱动）
const display = computed(() => {
  const cur = props.current;
  if (!cur || cur.status !== 'done') {
    return {
      grounded: cur ? '跑分中…' : '—',
      hallucination: '—',
      verdict: cur ? '跑分中…' : '—',
      guardDist: '—',
      elapsed: '—',
      sample: '—',
    };
  }
  const guard = Object.entries(cur.score.guard_dist ?? {})
    .map(([k, v]) => `${k}×${v}`)
    .join('、');
  return {
    grounded: String(cur.score.grounded),
    hallucination: String(cur.score.hallucination),
    verdict: cur.accept ? '达验收线可发布' : cur.pass ? '棘轮达标（验收线未达）' : '不达标禁发布',
    guardDist: guard || '无拦截',
    elapsed: `${(cur.elapsed_ms / 1000).toFixed(1)}s`,
    sample: `${cur.score.total} 条（采样 ${cur.limit}）`,
  };
});

const submitRun = () => {
  emit('run', { name: goldSet.value.trim(), limit: evalLimit.value });
};
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
