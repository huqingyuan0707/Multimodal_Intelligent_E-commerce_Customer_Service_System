// 对话反馈与埋点 composable（赞踩 → mining/feedback；行为 → governance/track；引用点击/错误气泡收口）
// 链路：ChatView/ChatMessage 事件 → 本模块 → @/api（submitFeedbackApi/trackEventApi）+ mock 兜底；
// 对齐页面设计 §3.1（赞踩/引用点击/埋点/错误状态完整性）+ API 规范 §4.4/§4.13
import { ElMessage } from 'element-plus';
import type { Ref } from 'vue';
import { submitFeedbackApi, trackEventApi } from '@/api';
import { mockChatFallback } from '@/mock';
import type { AgentMessage } from '@/types/agent';

export const useChatFeedback = (messages: Ref<AgentMessage[]>) => {
  // 行为埋点：fire-and-forget，失败静默（埋点绝不打扰买家操作；api 层已吞错，这里双保险）
  const track = (event: string, data: Record<string, unknown> = {}) => {
    trackEventApi(event, data).catch(() => undefined);
  };

  // 赞/踩反馈：差评进 Mining 待补知识；成功后置 message.feedback 置灰防重复
  const vote = async (m: AgentMessage, v: 'up' | 'down') => {
    if (m.feedback || !m.message_id) {
      return;
    }
    try {
      await submitFeedbackApi({ message_id: m.message_id, vote: v });
      m.feedback = v;
      track('chat.feedback', { vote: v });
    } catch (e) {
      ElMessage.error((e as Error).message || '反馈提交失败，请稍后重试');
    }
  };

  // 引用点击跳原文（知识库预览就绪后由画板升级路由跳转，现透出定位信息 + 埋点）
  const openDoc = (source: string) => {
    track('citation.click', { source: source.slice(0, 64) });
    ElMessage.info(`打开原文 ${source}（知识库预览就绪后跳转）`);
  };

  // 语音播放埋点（页面/组件在 play 事件处调用）
  const trackPlay = () => {
    track('voice.play', {});
  };

  // 流式错误收尾：限流（fatal）给排队话术不留重试；其余友好话术 + mock 兜底 + 可重试
  const handleStreamError = (msg: string, limited: boolean) => {
    if (limited) {
      ElMessage.warning(msg);
      messages.value = [
        ...messages.value,
        {
          id: `a-${Date.now()}`,
          role: 'agent',
          modality: 'text',
          content: `${msg}（排队中，稍候即好，无需重复发送）`,
        },
      ];
      return;
    }
    ElMessage.error(`${msg}，已用本地演示回复`);
    messages.value = [
      ...messages.value,
      {
        id: `a-${Date.now()}`,
        role: 'agent',
        modality: 'text',
        content: mockChatFallback,
        retryable: true,
      },
    ];
  };

  return { track, vote, openDoc, trackPlay, handleStreamError };
};
