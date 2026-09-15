<template>
  <div class="layout">
    <aside class="sider">
      <h3 class="sider-title">历史对话</h3>
      <SessionList
        :sessions="sessionStore.sessions"
        :current-id="sessionStore.currentId"
        :total="sessionStore.total"
        @new="newSession"
        @select="restore"
        @removed="onSessionRemoved"
        @page="onSessionPage"
        @size="onSessionSize"
      />
    </aside>
    <div class="page">
      <div class="top">
        <AiButton class="sess-btn" @click="openSessions">会话</AiButton>
      </div>
      <div ref="listRef" class="list" @scroll="onListScroll">
        <ChatSuggestions
          v-if="isEmpty"
          :empty="true"
          :welcome="welcomeSuggestions"
          :followups="[]"
          @ask="sendPreset"
        />
        <div v-if="hasMore" class="more-row">
          <AiButton @click="loadEarlier">加载更早消息</AiButton>
        </div>
        <ChatMessage
          v-for="m in messages"
          :key="m.id"
          :message="m"
          :show-followups="m.role === 'agent' && m.id === lastAgentId && !streaming"
          @ask="sendPreset"
          @preview="preview"
          @transfer="transfer"
        />
        <div v-if="streaming" class="bubble agent">
          <p class="content">{{ draft || phase || '思考中…' }}</p>
          <p v-if="sources.length" class="refs">来源：{{ sources.join(' / ') }}</p>
        </div>
      </div>
      <div v-if="pendingImages.length" class="thumbs">
        <div v-for="img in pendingImages" :key="img.id" class="thumb">
          <img :src="img.preview" alt="待发送图片" />
          <button class="x" :aria-label="`移除图片 ${img.id}`" @click="removeImage(img.id)">
            ×
          </button>
        </div>
      </div>
      <p v-if="imgError" class="err">{{ imgError }}</p>
      <VoicePanel v-if="voiceOpen" @transcribed="onTranscribed" />
      <ImagePreviewDialog ref="previewRef" />
      <div class="input-row">
        <AiInput v-model="input" placeholder="请输入问题，如：退货政策是什么" @keyup.enter="send" />
        <AiButton aria-label="上传图片" @click="pick">图片</AiButton>
        <AiButton aria-label="语音输入" @click="voiceOpen = !voiceOpen">语音</AiButton>
        <AiButton v-if="!streaming" @click="send">发送</AiButton>
        <AiButton v-else @click="stop">停止</AiButton>
        <AiButton :loading="transferring" @click="doTransfer">转人工</AiButton>
      </div>
      <input
        ref="fileRef"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        hidden
        aria-label="选择图片文件"
        @change="onPick"
      />
      <SessionDrawer
        ref="drawerRef"
        :sessions="sessionStore.sessions"
        :current-id="sessionStore.currentId"
        :total="sessionStore.total"
        @new="newSession"
        @select="restore"
        @removed="onSessionRemoved"
        @page="onSessionPage"
        @size="onSessionSize"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
// 真实对话：会话抽屉 + 图片上传 + 语音录播 + 流式落条（引用/trace/sources）；失败重连后仍不用回 mock 演示（对齐页面设计 §3.1/§4）
// 发送带 threadId（t- 占位不传）+ clientMsgId 幂等键，首轮 done 回 session_id 后认领替换占位。
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useAgentStream } from '@/composables/useAgentStream';
import { useHumanHandoff } from '@/composables/useHumanHandoff';
import { useChatHistory } from '@/composables/useChatHistory';
import { useImageUpload } from '@/composables/useImageUpload';
import { useStickToBottom } from '@/composables/useStickToBottom';
import { useSuggestedQuestions } from '@/composables/useSuggestedQuestions';
import ChatMessage from '@/components/ChatMessage.vue';
import ChatSuggestions from '@/components/ChatSuggestions.vue';
import ImagePreviewDialog from '@/components/ImagePreviewDialog.vue';
import SessionDrawer from '@/components/SessionDrawer.vue';
import SessionList from '@/components/SessionList.vue';
import VoicePanel from '@/components/VoicePanel.vue';
import { mockChatFallback } from '@/mock';
import { useSessionStore } from '@/stores/session';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AgentMessage, VisionInspection } from '@/types/agent';

const messages = ref<AgentMessage[]>([]);
const input = ref('');
const drawerRef = ref<{ open: () => unknown; close: () => unknown } | null>(null);
const fileRef = ref<HTMLInputElement | null>(null);
const sessionStore = useSessionStore();
const {
  hasMore,
  restore: restoreBase,
  loadEarlier,
  resetHistory,
  forgetSession,
} = useChatHistory(messages);

// 切会话恢复后给最后一条 Agent 回复挂追问（历史消息无 followups，前端按内容规则补）
const restore = async (id: string) => {
  await restoreBase(id);
  const list = [...messages.value].reverse();
  const last = list.find(m => m.role === 'agent');
  if (last && !last.followups?.length) {
    last.followups = getFollowups(last.content, last.references);
  }
};
const { streaming, sources, phase, draft, error, done, start, stop, toMessage } = useAgentStream();
const {
  images: pendingImages,
  error: imgError,
  addFiles,
  remove: removeImage,
  uploadAll,
  clear: clearImages,
} = useImageUpload();
const voiceOpen = ref(false);
const previewRef = ref<{ open: (url: string) => unknown } | null>(null);
// 流式增量粘底跟随（翻历史不抢滚动，对齐页面设计 §5）
const { listRef, onListScroll, stickNow } = useStickToBottom(() => messages.value.length, draft);
// 空态预设 + 追问延伸（欢迎卡 chips / 最后一条回复下猜你想问，点击直接发送）
const { getWelcomeSuggestions, getFollowups } = useSuggestedQuestions();
const welcomeSuggestions = getWelcomeSuggestions();
const isEmpty = computed(() => messages.value.length === 0 && !streaming.value);
const lastAgentId = computed(() => {
  const list = [...messages.value].reverse();
  return list.find(m => m.role === 'agent')?.id ?? '';
});

const preview = (url: string) => {
  previewRef.value?.open(url);
};

const onTranscribed = (p: { text: string }) => {
  input.value = p.text;
  voiceOpen.value = false;
};

const openSessions = () => {
  drawerRef.value?.open();
  sessionStore.loadSessions(1);
};

const onSessionPage = (p: number) => {
  sessionStore.loadSessions(p, sessionStore.size);
};

const onSessionSize = (s: number) => {
  sessionStore.loadSessions(1, s);
};

const newSession = () => {
  sessionStore.createLocalSession();
  resetHistory();
  drawerRef.value?.close();
};

const onSessionRemoved = (id: string) => {
  forgetSession(id);
};

const pick = () => {
  fileRef.value?.click();
};

const onPick = (e: Event) => {
  const files = (e.target as HTMLInputElement).files;
  if (files) {
    addFiles(files);
  }
  (e.target as HTMLInputElement).value = '';
};

const send = async () => {
  const query = input.value.trim();
  const attached = pendingImages.value.length;
  if ((!query && attached === 0) || streaming.value) {
    return;
  }
  // 先保证本地会话占位（t- 前缀），首轮 done 带回后端 id 后再认领替换
  const threadId = sessionStore.currentId ?? sessionStore.createLocalSession();
  const clientMsgId = `c-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
  const previews = pendingImages.value.map(i => i.preview);
  messages.value = [
    ...messages.value,
    {
      id: `u-${Date.now()}`,
      role: 'user',
      modality: attached > 0 ? 'image' : 'text',
      content: query + (attached > 0 ? `（附${attached}张图）` : ''),
      images: previews,
    },
  ];
  input.value = '';
  // 发送即回粘底，保证增量打字可见
  stickNow();
  // 上传即检测：检测卡随用户泡即时渲染，file_id/inspections 透传拼 LLM 上下文
  let imageIds: string[] = [];
  let inspections: VisionInspection[] = [];
  if (attached > 0) {
    const done = await uploadAll();
    if (done.length < attached) {
      ElMessage.warning('部分图片上传失败，已继续发送文字');
    }
    imageIds = done.map(d => d.file_id);
    inspections = done.map(d => d.inspection);
    messages.value = [
      ...messages.value,
      {
        id: `v-${Date.now()}`,
        role: 'agent',
        modality: 'image',
        content: '瑕疵检测结果',
        vision: inspections,
        need_human: inspections.some(v => v.need_human),
      },
    ];
    clearImages();
  }
  await start(query || '请看这几张图', {
    threadId: threadId.startsWith('t-') ? undefined : threadId,
    clientMsgId,
    imageIds,
    inspections,
  });
  if (error.value) {
    ElMessage.error(`${error.value}，已用本地演示回复`);
    messages.value = [
      ...messages.value,
      {
        id: `a-${Date.now()}`,
        role: 'agent',
        modality: 'text',
        content: mockChatFallback,
        followups: getFollowups(mockChatFallback),
      },
    ];
    return;
  }
  // 后端认领：t- 占位换成真实会话 id 并回填标题，抽屉列表随后刷新
  if (done.value?.session_id) {
    sessionStore.adoptSession(threadId, done.value.session_id, query.slice(0, 20) || '新会话');
    sessionStore.loadSessions();
  }
  const reply: AgentMessage = toMessage(`a-${Date.now()}`);
  reply.followups = getFollowups(reply.content, reply.references);
  messages.value = [...messages.value, reply];
};

// 预设问题 / 追问一键发送（复用 send 的图片与幂等链路，流式中禁用防并发）
const sendPreset = async (text: string) => {
  if (streaming.value || !text.trim()) {
    return;
  }
  input.value = text;
  await send();
};

// 转人工：买家自助挂起（useHumanHandoff 内置占位落库 + handoff + 系统提示行）
const { transferring, transfer } = useHumanHandoff();
const doTransfer = () =>
  transfer(content => {
    messages.value = [
      ...messages.value,
      { id: `s-${Date.now()}`, role: 'agent', modality: 'text', content },
    ];
  });

onMounted(() => {
  sessionStore.loadSessions();
});
</script>

<style scoped>
.layout {
  display: flex;
  height: 100%;
  min-height: 0;
}

.sider {
  width: 280px;
  flex-shrink: 0;
  padding: 16px 12px;
  overflow-y: auto;
  border-right: 1px solid var(--reai-border);
}

.sider-title {
  margin: 0 0 8px 4px;
  font-size: var(--reai-fs-title);
  font-weight: var(--reai-fw-semibold);
  line-height: var(--reai-lh-tight);
  color: var(--reai-text-main);
}

.sess-btn {
  display: none;
}

@media (max-width: 1023px) {
  .sider {
    display: none;
  }

  .sess-btn {
    display: inline-block;
  }
}

.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  width: min(960px, 100%);
  height: 100%;
  min-height: 0;
  padding: 16px;
  margin: 0 auto;
}

.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow-y: auto;
}

.bubble {
  max-width: 85%;
  padding: 10px 14px;
  font-size: var(--reai-fs-body);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-on-light);
  background: var(--reai-bubble-agent);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  /* 流式增量原文换行保留（white-space 可继承到气泡内 p.content） */
  white-space: pre-wrap;
}

/* 空态欢迎：之前无样式走浏览器默认宋体发虚，补字阶 */
.refs {
  margin: 8px 0 0;
  font-size: var(--reai-fs-caption);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-on-light-muted);
}

.thumbs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.thumb {
  position: relative;
  width: 72px;
  height: 72px;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 8px;
}

.thumb .x {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  padding: 0;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  cursor: pointer;
  color: var(--reai-text-on-brand);
  background: var(--reai-primary);
  border: none;
  border-radius: 50%;
}

.err {
  margin: 0;
  font-size: var(--reai-fs-caption);
  line-height: var(--reai-lh-body);
  color: var(--reai-notice);
}

.input-row {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}

.input-row > :first-child {
  flex: 1;
  min-width: 0;
}

.more-row {
  display: flex;
  justify-content: center;
}
</style>
