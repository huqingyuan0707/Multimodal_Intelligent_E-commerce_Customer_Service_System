// 历史恢复翻页（三层之 Message，对齐 API 规范 §4.3：详情倒序页 + has_more 加载更早）
// 后端倒序页渲染前反转；删除当前会话即清空消息区；页面只做编排。
import { ElMessage } from 'element-plus';
import { ref } from 'vue';
import type { Ref } from 'vue';
import { getSessionApi, toAgentMessages } from '@/api';
import { useSessionStore } from '@/stores/session';
import type { AgentMessage } from '@/types/agent';

const PAGE_SIZE = 50;

export const useChatHistory = (messages: Ref<AgentMessage[]>) => {
  const historyId = ref('');
  const historyPage = ref(1);
  const hasMore = ref(false);
  const sessionStore = useSessionStore();

  const resetHistory = () => {
    historyId.value = '';
    historyPage.value = 1;
    hasMore.value = false;
    messages.value = [];
  };

  const restore = async (id: string) => {
    try {
      const data = await getSessionApi({ id, page: 1, size: PAGE_SIZE });
      sessionStore.currentId = id;
      historyId.value = id;
      historyPage.value = 1;
      hasMore.value = data.has_more === true;
      messages.value = toAgentMessages(data.messages).reverse();
    } catch {
      ElMessage.error('会话恢复失败，已清空消息');
      resetHistory();
    }
  };

  const loadEarlier = async () => {
    if (!historyId.value || !hasMore.value) {
      return;
    }
    try {
      const data = await getSessionApi({
        id: historyId.value,
        page: historyPage.value + 1,
        size: PAGE_SIZE,
      });
      historyPage.value += 1;
      hasMore.value = data.has_more === true;
      messages.value = [...toAgentMessages(data.messages).reverse(), ...messages.value];
    } catch {
      ElMessage.error('更早消息加载失败');
    }
  };

  const forgetSession = (id: string) => {
    if (historyId.value === id) {
      resetHistory();
    }
  };

  return { hasMore, restore, loadEarlier, resetHistory, forgetSession };
};
