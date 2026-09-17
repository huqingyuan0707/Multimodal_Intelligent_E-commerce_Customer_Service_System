// 对话发送管线（send / 重试 / 预设 / 快捷入口回执，从 ChatView 抽出守 400 行红线）
// 链路：ChatView 组合 → 本模块（用户泡落条 + 图片上传检测 + 幂等流式 + done 认领 + 错误收尾）
//       → useAgentStream/useChatHistory/useImageUpload/useChatFeedback + stores/session；
// 对齐页面设计 §3.1：t- 占位认领、clientMsgId 幂等重放、错误气泡重试、限流排队话术、埋点。
import { ElMessage } from 'element-plus';
import { ref } from 'vue';
import type { Ref } from 'vue';
import type { useAgentStream } from '@/composables/useAgentStream';
import type { useChatFeedback } from '@/composables/useChatFeedback';
import type { useImageUpload } from '@/composables/useImageUpload';
import { useSessionStore } from '@/stores/session';
import type { AgentMessage, VisionInspection } from '@/types/agent';

type StreamApi = ReturnType<typeof useAgentStream>;
type FeedbackApi = ReturnType<typeof useChatFeedback>;
type UploadApi = ReturnType<typeof useImageUpload>;

export type SendDeps = {
  messages: Ref<AgentMessage[]>;
  input: Ref<string>;
  stream: StreamApi;
  feedback: FeedbackApi;
  upload: UploadApi;
  stickNow: () => unknown;
  getFollowups: (answer: string, refs?: AgentMessage['references']) => string[];
};

// 最近一轮发送参数（重试复用同一 clientMsgId，后端幂等重放不翻倍）
export type LastTurn = {
  query: string;
  clientMsgId: string;
  imageIds: string[];
  inspections: VisionInspection[];
};

export const useChatSend = (deps: SendDeps) => {
  const { messages, input, stream, feedback, upload, stickNow, getFollowups } = deps;
  const sessionStore = useSessionStore();
  const lastTurn: Ref<LastTurn | null> = ref(null);

  const pushMessage = (m: AgentMessage) => {
    messages.value = [...messages.value, m];
  };

  // 流式收尾：错误统一交 feedback.handleStreamError（限流排队 / 可重试话术），成功落 Agent 气泡
  const settle = async (threadId: string, query: string) => {
    if (stream.error.value) {
      feedback.handleStreamError(stream.error.value, stream.limited.value);
      return;
    }
    if (stream.done.value?.session_id) {
      sessionStore.adoptSession(
        threadId,
        stream.done.value.session_id,
        query.slice(0, 20) || '新会话',
      );
      sessionStore.loadSessions();
    }
    const reply = stream.toMessage(`a-${Date.now()}`) as AgentMessage;
    reply.followups = getFollowups(reply.content, reply.references);
    pushMessage(reply);
  };

  const send = async () => {
    const query = input.value.trim();
    const attached = upload.images.value.length;
    if ((!query && attached === 0) || stream.streaming.value) {
      return;
    }
    // 先保证本地会话占位（t- 前缀），首轮 done 带回后端 id 后再认领替换
    const threadId = sessionStore.currentId ?? sessionStore.createLocalSession();
    const clientMsgId = `c-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    feedback.track('chat.send', { len: query.length, images: attached });
    pushMessage({
      id: `u-${Date.now()}`,
      role: 'user',
      modality: attached > 0 ? 'image' : 'text',
      content: query + (attached > 0 ? `（附${attached}张图）` : ''),
      images: upload.images.value.map(i => i.preview),
    });
    input.value = '';
    stickNow();
    // 上传即检测：检测卡随用户泡即时渲染，file_id/inspections 透传拼 LLM 上下文
    let imageIds: string[] = [];
    let inspections: VisionInspection[] = [];
    if (attached > 0) {
      const uploaded = await upload.uploadAll();
      feedback.track('image.upload', { count: uploaded.length });
      if (uploaded.length < attached) {
        ElMessage.warning('部分图片上传失败，已继续发送文字');
      }
      imageIds = uploaded.map(d => d.file_id);
      inspections = uploaded.map(d => d.inspection);
      pushMessage({
        id: `v-${Date.now()}`,
        role: 'agent',
        modality: 'image',
        content: '瑕疵检测结果',
        vision: inspections,
        need_human: inspections.some(v => v.need_human),
      });
      upload.clear();
    }
    const askText = query || '请看这几张图';
    lastTurn.value = { query: askText, clientMsgId, imageIds, inspections };
    await stream.start(askText, {
      threadId: threadId.startsWith('t-') ? undefined : threadId,
      clientMsgId,
      imageIds,
      inspections,
    });
    await settle(threadId, query);
  };

  // 重试（错误气泡按钮）：同一 clientMsgId 重发，后端幂等重放不翻倍
  const retry = async () => {
    const last = lastTurn.value;
    if (!last || stream.streaming.value) {
      return;
    }
    messages.value = messages.value.filter(m => !m.retryable);
    await stream.start(last.query, {
      threadId: sessionStore.currentId?.startsWith('t-') ? undefined : sessionStore.currentId,
      clientMsgId: last.clientMsgId,
      imageIds: last.imageIds,
      inspections: last.inspections,
    });
    await settle(sessionStore.currentId ?? '', last.query);
  };

  // 预设问题 / 追问一键发送（复用 send 的幂等链路，流式中禁用防并发）
  const sendPreset = async (text: string) => {
    if (stream.streaming.value || !text.trim()) {
      return;
    }
    input.value = text;
    await send();
  };

  // 快捷入口提交回执（退换申请等）：追加一条系统提示行 + 埋点
  const noticeLine = (content: string) => {
    feedback.track('quick.notice', {});
    pushMessage({ id: `n-${Date.now()}`, role: 'agent', modality: 'text', content });
  };

  return { send, retry, sendPreset, noticeLine, lastTurn };
};
