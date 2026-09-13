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
      />
    </aside>
    <div class="page">
      <div class="top">
        <h2>对话助手</h2>
        <AiButton class="sess-btn" @click="openSessions">会话</AiButton>
      </div>
    <div class="list">
      <div v-if="hasMore" class="more-row">
        <AiButton @click="loadEarlier">加载更早消息</AiButton>
      </div>
      <div v-for="m in messages" :key="m.id" class="bubble" :class="m.role">
        <div v-if="m.images?.length" class="thumbs">
          <img
            v-for="(u, i) in m.images"
            :key="`${m.id}-${i}`"
            :src="u"
            alt="售后图片"
            @click="preview(u)"
          />
        </div>
        <p class="content">{{ m.content }}</p>
        <VisionResultCard v-if="m.vision?.length" :inspections="m.vision" />
        <p v-if="m.need_human" class="human">
          置信不足已转人工复核，坐席将在 30 秒内接管
          <AiButton @click="transfer">立即转人工</AiButton>
        </p>
        <p v-if="m.references?.length" class="refs">
          引用：
          <span v-for="r in m.references" :key="r.source">[{{ r.title }}]</span>
        </p>
        <p v-if="m.trace_id" class="trace">trace: {{ m.trace_id }}</p>
        <p v-if="m.context" class="trace">
          上下文 {{ m.context.rounds }} 轮/约 {{ m.context.tokens }} token{{
            m.context.summarized ? '（已摘要）' : ''
          }}
        </p>
      </div>
      <div v-if="streaming" class="bubble agent">
        <p class="content">{{ draft || phase || '思考中…' }}</p>
        <p v-if="sources.length" class="refs">来源：{{ sources.join(' / ') }}</p>
      </div>
    </div>
    <div v-if="pendingImages.length" class="thumbs">
      <div v-for="img in pendingImages" :key="img.id" class="thumb">
        <img :src="img.preview" alt="待发送图片" />
        <span class="x" @click="removeImage(img.id)">×</span>
      </div>
    </div>
    <p v-if="imgError" class="err">{{ imgError }}</p>
    <VoicePanel v-if="voiceOpen" @transcribed="onTranscribed" />
    <ImagePreviewDialog ref="previewRef" />
    <div class="input-row">
      <AiInput v-model="input" placeholder="请输入问题，如：退货政策是什么" @keyup.enter="send" />
      <AiButton @click="pick">图片</AiButton>
      <AiButton @click="voiceOpen = !voiceOpen">语音</AiButton>
      <AiButton v-if="!streaming" @click="send">发送</AiButton>
      <AiButton v-else @click="stop">停止</AiButton>
      <AiButton @click="transfer">转人工</AiButton>
    </div>
    <input
      ref="fileRef"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      hidden
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
      />
    </div>
  </div>
</template>

<script setup lang="ts">
// 真实对话：会话抽屉 + 图片上传 + 语音录播 + 流式落条（引用/trace/sources）；失败重连后仍不用回 mock 演示（对齐页面设计 §3.1/§4）
// 发送带 threadId（t- 占位不传）+ clientMsgId 幂等键，首轮 done 回 session_id 后认领替换占位。
import { ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { useAgentStream } from '@/composables/useAgentStream';
import { useChatHistory } from '@/composables/useChatHistory';
import { useImageUpload } from '@/composables/useImageUpload';
import ImagePreviewDialog from '@/components/ImagePreviewDialog.vue';
import SessionDrawer from '@/components/SessionDrawer.vue';
import SessionList from '@/components/SessionList.vue';
import VisionResultCard from '@/components/VisionResultCard.vue';
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
const { hasMore, restore, loadEarlier, resetHistory, forgetSession } = useChatHistory(messages);
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
  sessionStore.loadSessions(p);
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
      { id: `a-${Date.now()}`, role: 'agent', modality: 'text', content: mockChatFallback },
    ];
    return;
  }
  // 后端认领：t- 占位换成真实会话 id 并回填标题，抽屉列表随后刷新
  if (done.value?.session_id) {
    sessionStore.adoptSession(threadId, done.value.session_id, query.slice(0, 20) || '新会话');
    sessionStore.loadSessions();
  }
  messages.value = [...messages.value, toMessage(`a-${Date.now()}`)];
};

const transfer = () => {
  messages.value = [
    ...messages.value,
    {
      id: `s-${Date.now()}`,
      role: 'agent',
      modality: 'text',
      content: '已为你转人工，坐席将在 30 秒内接管（演示占位）。',
    },
  ];
};

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
  font-size: 15px;
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

.top h2 {
  margin: 0;
  color: var(--reai-text-main);
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
  padding: 8px 12px;
  color: var(--reai-text-on-light);
  background: var(--reai-bubble-agent);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
}

.bubble.user {
  align-self: flex-end;
  color: var(--reai-nav-active);
  background: var(--reai-bubble-user);
}

.refs,
.trace {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.thumbs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.list .thumbs img {
  width: 72px;
  height: 72px;
  cursor: zoom-in;
  object-fit: cover;
  border-radius: 8px;
}

.human {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--reai-notice);
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
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  cursor: pointer;
  color: var(--reai-nav-active);
  background: var(--reai-primary);
  border-radius: 50%;
}

.err {
  margin: 0;
  font-size: 12px;
  color: var(--reai-notice);
}

.voice-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  color: var(--reai-text-main);
}

.rec-dot {
  width: 10px;
  height: 10px;
  background: var(--reai-notice);
  border-radius: 50%;
  animation: blink 1s infinite;
}

.player {
  max-width: 240px;
  height: 32px;
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

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
</style>
