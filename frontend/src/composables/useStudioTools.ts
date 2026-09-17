// Studio 工具试调数据（清单 + 沙箱试调，对齐 API 规范 §4.12；与 ToolCallCard 同源）
// 失败向上传播（页面 catch 回 mock 兜底），试调参数非 JSON 直接抛中文错
import { ref } from 'vue';
import { invokeToolApi, listToolsApi } from '@/api';
import type { StudioTool, ToolCall } from '@/types/agent';

export const useStudioTools = () => {
  const tools = ref<StudioTool[]>([]);
  const total = ref(0);
  const loading = ref(false);
  const trialing = ref(false);

  const refresh = async () => {
    loading.value = true;
    try {
      const data = (await listToolsApi()) as { total: number; items: StudioTool[] };
      tools.value = data.items;
      total.value = data.total;
      return tools.value;
    } finally {
      loading.value = false;
    }
  };

  // 沙箱试调：argsText 为 JSON 文本（空即 {}），非法 JSON 抛中文错由页面提示
  const trial = async (name: string, argsText: string) => {
    let args: object = {};
    try {
      args = argsText.trim() ? (JSON.parse(argsText) as object) : {};
    } catch {
      throw new Error('试调参数不是合法 JSON，请检查后重试');
    }
    if (args === null || typeof args !== 'object' || Array.isArray(args)) {
      throw new Error('试调参数必须是 JSON 对象');
    }
    trialing.value = true;
    try {
      return (await invokeToolApi({ name, args })) as ToolCall;
    } finally {
      trialing.value = false;
    }
  };

  return { tools, total, loading, trialing, refresh, trial };
};
