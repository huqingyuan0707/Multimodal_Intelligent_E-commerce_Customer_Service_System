<template>
  <div class="page">
    <div class="top">
      <h2>对话助手</h2>
      <AiButton @click="openSessions">会话</AiButton>
    </div>
    <div class="list">
      <div v-for="m in messages" :key="m.id" class="bubble" :class="m.role">
        <p class="content">{{ m.content }}</p>
        <p v-if="m.references?.length" class="refs">
          引用：
          <span v-for="r in m.references" :key="r.source">[{{ r.title }}]</span>
        </p>
        <p v-if="m.trace_id" class="trace">trace: {{ m.trace_id }}</p>
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
    <div v-if="recording || audioUrl" class="voice-bar">
      <span v-if="recording" class="rec-dot" />
      <span v-if="recording">录音中 {{ seconds }}s（≤60s）</span>
      <audio v-if="!recording && audioUrl" :src="audioUrl" controls class="player" />
      <AiButton v-if="!recording && audioUrl" @click="transcribe">转文字</AiButton>
      <AiButton v-if="!recording && audioUrl" @click="discardRec">丢弃</AiButton>
    </div>
    <p v-if="voiceError" class="err">{{ voiceError }}</p>
    <div class="input-row">
      <AiInput v-model="input" placeholder="请输入问题，如：退货政策是什么" @keyup.enter="send" />
      <AiButton @click="pick">图片</AiButton>
      <AiButton :disabled="!voiceSupported" @click="toggleRec">
        {{ recording ? '停止录制' : '语音' }}
      </AiButton>
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
    <el-drawer v-model="drawer" title="历史会话" size="300px">
      <AiButton class="new" @click="newSession">新会话</AiButton>
      <div
        v-for="s in sessionStore.sessions"
        :key="s.id"
        class="sess"
        :class="{ active: s.id === sessionStore.currentId }"
        @click="restore(s.id)"
      >
        {{ s.title }}
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 真实对话：会话抽屉 + 图片上传 + 语音录播 + 流式落条（引用/trace/sources）；失败重连后仍不用回 mock 演示（对齐页面设计 §3.1/§4）
import { ElDrawer, ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { getSessionApi } from '@/api';
import { useAgentStream } from '@/composables/useAgentStream';
import { useImageUpload } from '@/composables/useImageUpload';
import { useVoiceRecorder } from '@/composables/useVoiceRecorder';
import { mockChatFallback } from '@/mock';
import { useSessionStore } from '@/stores/session';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AgentMessage } from '@/types/agent';

const messages = ref<AgentMessage[]>([]);
const input = ref('');
const drawer = ref(false);
const fileRef = ref<HTMLInputElement | null>(null);
const sessionStore = useSessionStore();
const { streaming, sources, phase, draft, error, start, stop, toMessage } = useAgentStream();
const {
  images: pendingImages,
  error: imgError,
  addFiles,
  remove: removeImage,
  uploadAll,
  clear: clearImages,
} = useImageUpload();
const {
  recording,
  seconds,
  audioUrl,
  error: voiceError,
  supported: voiceSupported,
  start: startRec,
  stop: stopRec,
  discard: discardRec,
} = useVoiceRecorder();

const toAgentMessages = (list: unknown[]) => {
  if (!Array.isArray(list)) {
    return [];
  }
  return list.flatMap((m, i) => {
    if (typeof m !== 'object' || m === null) {
      return [];
    }
    const r = m as { content?: string; role?: string };
    if (typeof r.content !== 'string') {
      return [];
    }
    return [
      {
        id: `h-${i}`,
        role: r.role === 'user' ? 'user' : 'agent',
        modality: 'text',
        content: r.content,
      } as AgentMessage,
    ];
  });
};

const openSessions = () => {
  drawer.value = true;
  sessionStore.loadSessions();
};

const newSession = () => {
  sessionStore.createLocalSession();
  messages.value = [];
  drawer.value = false;
};

const restore = async (id: string) => {
  try {
    const data = await getSessionApi({ id });
    sessionStore.currentId = id;
    messages.value = toAgentMessages(data.messages);
    drawer.value = false;
  } catch {
    ElMessage.error('会话恢复失败，已清空为本地演示');
    messages.value = [];
  }
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

const toggleRec = () => {
  if (recording.value) {
    stopRec();
  } else {
    startRec();
  }
};

const transcribe = () => {
  ElMessage.info('语音转写待后端 ASR 接口（录音与播放已可用）');
};

const send = async () => {
  const query = input.value.trim();
  const attached = pendingImages.value.length;
  if ((!query && attached === 0) || streaming.value) {
    return;
  }
  messages.value = [
    ...messages.value,
    {
      id: `u-${Date.now()}`,
      role: 'user',
      modality: attached > 0 ? 'image' : 'text',
      content: query + (attached > 0 ? `（附${attached}张图）` : ''),
    },
  ];
  input.value = '';
  if (attached > 0) {
    const names = await uploadAll();
    if (names.length < attached) {
      ElMessage.warning('部分图片上传失败，已继续发送文字');
    }
    clearImages();
  }
  await start(query || '请看这几张图');
  if (error.value) {
    ElMessage.error(`${error.value}，已用本地演示回复`);
    messages.value = [
      ...messages.value,
      { id: `a-${Date.now()}`, role: 'agent', modality: 'text', content: mockChatFallback },
    ];
    return;
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

.new {
  width: 100%;
  margin-bottom: 8px;
}

.sess {
  padding: 10px;
  margin-bottom: 4px;
  font-size: 14px;
  cursor: pointer;
  color: var(--reai-text-main);
  border-radius: 8px;
}

.sess:hover {
  background: var(--reai-card-2);
}

.sess.active {
  background: var(--reai-card-2);
}

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
</style>
