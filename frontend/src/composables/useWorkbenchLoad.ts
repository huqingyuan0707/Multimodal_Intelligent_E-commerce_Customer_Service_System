// 坐席负载面板数据（FR-7 技能组 + 负载均衡）：GET /workbench/load → 技能组清单/分配开关/坐席在手数
// 失败静默降级（skillGroups 空即隐藏筛选，assignEnabled=false 即禁用智能分配按钮），不弹错不阻塞队列
// 对齐 API 规范 §4.11 + 页面设计 §3.2
import { computed, ref } from 'vue';
import { loadWorkbenchApi } from '@/api';
import type { WorkbenchLoad } from '@/api';

export const useWorkbenchLoad = () => {
  const panel = ref<WorkbenchLoad | null>(null);
  const loading = ref(false);

  // 技能组筛选清单：接口不可用时为空数组 → 组件隐藏该行（不硬编码组名，口径跟随后端 Settings）
  const skillGroups = computed(() => panel.value?.skill_groups ?? []);
  const assignEnabled = computed(() => panel.value?.enabled ?? false);
  const loadLimit = computed(() => panel.value?.limit ?? 0);
  const agents = computed(() => panel.value?.agents ?? []);
  const pendingBySkill = computed(() => panel.value?.pending_by_skill ?? {});

  const refresh = async () => {
    loading.value = true;
    try {
      panel.value = (await loadWorkbenchApi()) as WorkbenchLoad;
    } catch {
      panel.value = null;
    } finally {
      loading.value = false;
    }
    return panel.value;
  };

  return {
    panel,
    loading,
    skillGroups,
    assignEnabled,
    loadLimit,
    agents,
    pendingBySkill,
    refresh,
  };
};
