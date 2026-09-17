// Studio 评测一键跑（建 run + 轮询 + 历史，对齐 API 规范 §4.13）
// 失败向上传播（页面 catch 回 mock 兜底）；轮询页切走即停（cancelled 防内存泄漏）
import { onUnmounted, ref } from 'vue';
import { createEvalRunApi, getEvalRunApi, listEvalRunsApi } from '@/api';
import type { EvalPage, EvalRun } from '@/types/agent';

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_TRIES = 90;

export const useStudioEval = () => {
  const runs = ref<EvalRun[]>([]);
  const total = ref(0);
  const page = ref(1);
  const size = ref(20);
  const current = ref<EvalRun | null>(null);
  const loading = ref(false);
  const running = ref(false);
  const cancelled = ref(false);

  onUnmounted(() => {
    cancelled.value = true;
  });

  const refreshRuns = async (nextPage?: number, nextSize?: number) => {
    if (nextPage !== undefined) page.value = nextPage;
    if (nextSize !== undefined) size.value = nextSize;
    loading.value = true;
    try {
      const data = (await listEvalRunsApi({ page: page.value, size: size.value })) as EvalPage;
      runs.value = data.items;
      total.value = data.total;
      return runs.value;
    } finally {
      loading.value = false;
    }
  };

  // 一键跑：建 run 即返，随后轮询到 done/failed（pending/running 为中间态，不算失败）
  const startRun = async (name: string, limit: number) => {
    running.value = true;
    try {
      const created = (await createEvalRunApi({ name, limit })) as EvalRun;
      current.value = created;
      return await pollRun(created.id);
    } finally {
      running.value = false;
    }
  };

  const pollRun = async (id: string) => {
    for (let i = 0; i < POLL_MAX_TRIES; i += 1) {
      if (cancelled.value) return current.value;
      const detail = (await getEvalRunApi({ id })) as EvalRun;
      current.value = detail;
      if (detail.status === 'done' || detail.status === 'failed') return detail;
      await new Promise(resolve => {
        setTimeout(resolve, POLL_INTERVAL_MS);
      });
    }
    throw new Error('评测超时，请稍后在历史记录中查看结果');
  };

  return { runs, total, page, size, current, loading, running, refreshRuns, startRun, pollRun };
};
