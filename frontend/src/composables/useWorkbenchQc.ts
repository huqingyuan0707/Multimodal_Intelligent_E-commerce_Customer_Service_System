// 坐席质检评分（FR-7 质检打分）：resolved 会话自动评分读取 + 人工改评
// 链路：切到 resolved 会话 → GET score 展示（judge/rule/manual 来源可回溯）→ 改评 POST score 覆盖
// 失败回退空态 + demo 标（不阻塞工作台主链路）；对齐 API 规范 §4.11 + 页面设计 §3.2
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { getScoreWorkbenchApi, saveScoreWorkbenchApi } from '@/api';
import type { WorkbenchScore } from '@/api';

export type QcSavePayload = {
  score: number;
  resolution_ok: boolean;
  comment: string;
};

export const useWorkbenchQc = () => {
  const score = ref<WorkbenchScore | null>(null);
  const loading = ref(false);
  const saving = ref(false);
  const demo = ref(false);

  const load = async (id: string) => {
    if (!id) {
      score.value = null;
      return;
    }
    loading.value = true;
    try {
      score.value = (await getScoreWorkbenchApi({ id })) as WorkbenchScore;
      demo.value = false;
    } catch {
      score.value = null;
      demo.value = true;
    } finally {
      loading.value = false;
    }
  };

  // 人工改评：成功后用返回值刷新卡片（source=manual + reviewer 留痕）
  const save = async (id: string, payload: QcSavePayload) => {
    if (!id) {
      return false;
    }
    saving.value = true;
    try {
      score.value = (await saveScoreWorkbenchApi({ id, ...payload })) as WorkbenchScore;
      ElMessage.success('质检评分已更新');
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '评分保存失败');
      return false;
    } finally {
      saving.value = false;
    }
  };

  const reset = () => {
    score.value = null;
    demo.value = false;
  };

  return { score, loading, saving, demo, load, save, reset };
};
