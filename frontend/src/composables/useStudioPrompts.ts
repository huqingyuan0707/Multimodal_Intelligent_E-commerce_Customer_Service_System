// Studio Prompt 版本数据（列表/新建/发布/调灰/回滚/线上读取，对齐 API 规范 §4.13）
// 失败向上传播（页面 catch 后中文提示），本层只管 loading 与状态映射
import { computed, ref } from 'vue';
import {
  createPromptApi,
  listPromptsApi,
  onlinePromptApi,
  publishPromptApi,
  rollbackPromptApi,
  setGrayPromptApi,
} from '@/api';
import type { PromptPage, PromptVersion } from '@/types/agent';

export const useStudioPrompts = () => {
  const versions = ref<PromptVersion[]>([]);
  const total = ref(0);
  const page = ref(1);
  const size = ref(20);
  const online = ref<PromptVersion | null>(null);
  const loading = ref(false);

  // 是否有线上版本（发布/回滚按钮可用性不依赖它，空租户允许首发）
  const hasOnline = computed(() => online.value !== null);

  const refresh = async (nextPage?: number, nextSize?: number) => {
    if (nextPage !== undefined) page.value = nextPage;
    if (nextSize !== undefined) size.value = nextSize;
    loading.value = true;
    try {
      const data = (await listPromptsApi({ page: page.value, size: size.value })) as PromptPage;
      versions.value = data.items;
      total.value = data.total;
      return versions.value;
    } finally {
      loading.value = false;
    }
  };

  const refreshOnline = async () => {
    online.value = (await onlinePromptApi()) as PromptVersion | null;
    return online.value;
  };

  const create = async (desc: string, content: string) => {
    const row = (await createPromptApi({ desc, content })) as PromptVersion;
    await refresh(1);
    return row;
  };

  const publish = async (version: string, gray: number) => {
    const row = (await publishPromptApi({ version, gray })) as PromptVersion;
    await refresh();
    await refreshOnline();
    return row;
  };

  const setGray = async (version: string, gray: number) => {
    const row = (await setGrayPromptApi({ version, gray })) as PromptVersion;
    await refresh();
    return row;
  };

  const rollback = async (version: string) => {
    const row = (await rollbackPromptApi({ version })) as PromptVersion;
    await refresh();
    await refreshOnline();
    return row;
  };

  return {
    versions,
    total,
    page,
    size,
    online,
    hasOnline,
    loading,
    refresh,
    refreshOnline,
    create,
    publish,
    setGray,
    rollback,
  };
};
