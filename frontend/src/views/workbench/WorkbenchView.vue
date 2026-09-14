<template>
  <div class="workbench">
    <!-- 左：会话队列（搜索＋未读徽标＋VIP置顶，画布 sessionList） -->
    <section class="queue card">
      <div class="queue-head">
        <h3 class="card-title">会话队列</h3>
        <span class="badge">{{ unread }}</span>
      </div>
      <AiInput v-model="keyword" placeholder="搜索会话 / 订单号" clearable class="search" />
      <div
        v-for="s in filteredSessions"
        :key="s.id"
        class="session"
        :class="{ active: s.id === currentId }"
        @click="select(s.id)"
      >
        <span class="avatar">{{ s.name.charAt(0) }}</span>
        <span class="info">
          <span class="name">{{ s.name }}</span>
          <span class="summary">{{ s.tag }}</span>
        </span>
        <el-tag v-if="s.vip" size="small" type="warning">VIP</el-tag>
      </div>
    </section>

    <!-- 中：当前会话（顶栏＋消息流＋快捷回复＋输入行，画布 chatPanel） -->
    <section class="chat card">
      <div class="chat-head">
        <span class="avatar">{{ currentName.charAt(0) || '客' }}</span>
        <span class="meta">
          <span class="name">{{ currentName }}</span>
          <span class="online">在线 · 咨询中</span>
        </span>
        <AiButton class="transfer" @click="transfer">转人工</AiButton>
      </div>
      <div class="msgs">
        <p v-if="phaseText" class="phase">{{ phaseText }}</p>
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <template v-if="m.role === 'agent'">
            <span class="avatar agent">AI</span>
            <div class="bubble">
              <p class="text">{{ m.content || '思考中…' }}</p>
              <VisionResultCard :inspections="m.vision ?? []" />
              <CitationList :refs="m.references ?? []" :trace-id="m.trace_id" @open="openDoc" />
            </div>
          </template>
          <template v-else>
            <div v-if="m.modality === 'voice'" class="bubble voice">
              <button class="play" @click="playVoice(m.id)">▶</button>
              <span class="wave"><i /></span>
              <span class="vmeta">{{ voiceText(m.id) }}</span>
            </div>
            <p v-else class="bubble user">{{ m.content }}</p>
            <span class="avatar">{{ currentName.charAt(0) || '客' }}</span>
          </template>
        </div>
      </div>
      <div class="quicks">
        <button v-for="q in QUICK_REPLIES" :key="q" class="quick" @click="applyQuick(q)">
          {{ q }}
        </button>
      </div>
      <div class="input-row">
        <AiButton @click="pickImage">图片</AiButton>
        <AiButton @click="recordVoice">语音</AiButton>
        <AiInput
          v-model="draft"
          placeholder="输入消息，支持发送图片描述问题…"
          class="grow"
          @keyup.enter="send"
        />
        <AiButton type="primary" :loading="streaming" @click="send">发送</AiButton>
      </div>
    </section>

    <!-- 右：订单卡＋AI 辅助（画布 sidePanel） -->
    <WorkbenchSide @fill="draft = $event" />
  </div>
</template>

<script setup lang="ts">
// 坐席工作台三栏（队列｜会话流＋VLM蓝卡＋引用金卡＋语音行｜订单＋AI辅助），对齐画布屏一与页面设计 §3.2
// 数据：队列走 mock（后端队列接口就绪前占位）；历史优先调 getSessionApi，404 回退演示；发送走 useAgentStream 真流式
import { ElMessage, ElMessageBox, ElTag } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { getSessionApi, toAgentMessages } from '@/api';
import CitationList from '@/components/CitationList.vue';
import VisionResultCard from '@/components/VisionResultCard.vue';
import WorkbenchSide from '@/components/WorkbenchSide.vue';
import { mockWorkbenchSeed, mockWorkSessions } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { useAgentStream } from '@/composables/useAgentStream';
import type { AgentMessage } from '@/types/agent';

// 流式阶段中文映射（后端 phase 原语：retrieving/generating/validating）
const PHASE_TAG = {
  retrieving: '检索中…',
  generating: '生成中…',
  validating: '校验引用中…',
} as const;
// 快捷回复（转人工走确认框，其余填入输入框）
const QUICK_REPLIES = ['查物流', '退换货', '转人工'] as const;
// 语音演示元数据（时长·转写置信度；真语音链路接通后随消息下发）
const VOICE_META = { 'v-1': '0:12 · 转写0.91' } as const;

const sessions = ref([...mockWorkSessions]);
const currentId = ref(mockWorkSessions[0]?.id ?? '');
const keyword = ref('');
const draft = ref('');
const messages = ref<AgentMessage[]>([]);
const stream = useAgentStream();
const streaming = stream.streaming;

const unread = computed(() => sessions.value.length);
const filteredSessions = computed(() => {
  const k = keyword.value.trim();
  if (!k) return sessions.value;
  return sessions.value.filter(s => s.name.includes(k) || s.tag.includes(k));
});
const currentName = computed(() => sessions.value.find(s => s.id === currentId.value)?.name ?? '');
const phaseText = computed(() => {
  const p = stream.phase.value;
  if (stream.streaming.value && p in PHASE_TAG) return PHASE_TAG[p as keyof typeof PHASE_TAG];
  if (stream.streaming.value) return p || '请求中…';
  return '';
});
const voiceText = (id: string) =>
  id in VOICE_META ? VOICE_META[id as keyof typeof VOICE_META] : '';

// 切会话：mock 队列直接用种子；后端 id 拉历史（含引用/trace/检测卡），失败回退演示
const loadHistory = async (id: string) => {
  if (id.startsWith('w-')) {
    messages.value = mockWorkbenchSeed();
    return;
  }
  try {
    const data = (await getSessionApi({ id })) as { messages?: unknown[] };
    const list = Array.isArray(data?.messages) ? toAgentMessages(data.messages) : [];
    messages.value = list.length ? list : mockWorkbenchSeed();
  } catch {
    messages.value = mockWorkbenchSeed();
  }
};

const select = (id: string) => {
  if (stream.streaming.value) stream.stop();
  currentId.value = id;
  loadHistory(id);
};

const send = async () => {
  const content = draft.value.trim();
  if (!content || stream.streaming.value) return;
  const key = `c-${Date.now()}`;
  messages.value = [...messages.value, { id: key, role: 'user', modality: 'text', content }];
  draft.value = '';
  const target = `a-${key}`;
  messages.value = [
    ...messages.value,
    { id: target, role: 'agent', modality: 'text', content: '' },
  ];
  await stream.start(content, { clientMsgId: key });
  const final = stream.toMessage(target);
  messages.value = messages.value.map(m => (m.id === target ? { ...final, id: target } : m));
  if (stream.error.value) ElMessage.error(stream.error.value);
};

const applyQuick = (q: string) => {
  if (q === '转人工') {
    transfer();
    return;
  }
  draft.value = q;
};

const transfer = () => {
  ElMessageBox.confirm('确认为当前会话转人工？', '转人工', {
    confirmButtonText: '确认',
    cancelButtonText: '取消',
  })
    .then(() => ElMessage.success('已转人工，坐席即将接管（演示占位）'))
    .catch(() => undefined);
};

const pickImage = () => ElMessage.info('图片上传后续接多模态接口（演示占位，≤9张/单张≤10M）');
const recordVoice = () => ElMessage.info('按住录音 ≤60s（演示占位）');
const playVoice = (id: string) => ElMessage.info(`播放语音 ${id}（演示占位）`);
const openDoc = (source: string) => ElMessage.info(`打开原文 ${source}（知识库预览就绪后跳转）`);

onMounted(() => {
  loadHistory(currentId.value);
});
</script>

<style scoped>
.workbench {
  display: flex;
  gap: 16px;
  height: 100%;
  min-height: 0;
}
.card {
  padding: 16px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}
.card-title {
  margin: 0;
  font-size: 15px;
  color: var(--reai-text-main);
}
.queue {
  display: flex;
  flex: 0 1 300px;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.badge {
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: #ff5a36;
  border-radius: 999px;
}
.session {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px;
  cursor: pointer;
  border-radius: 10px;
}
.session:hover,
.session.active {
  background: var(--reai-card-2);
}
.avatar {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 14px;
  color: var(--reai-nav-active);
  background: var(--reai-primary);
  border-radius: 50%;
}
.avatar.agent {
  font-size: 12px;
  color: var(--reai-text-on-light);
  background: var(--reai-accent);
}
.info {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.name {
  font-size: 13px;
  font-weight: 600;
  color: var(--reai-text-main);
}
.summary {
  font-size: 12px;
  color: var(--reai-text-muted);
}
.chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.chat-head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--reai-border);
}
.meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.online {
  font-size: 11px;
  color: var(--reai-online);
}
.msgs {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  padding: 16px 4px;
  overflow-y: auto;
}
.phase {
  margin: 0;
  font-size: 12px;
  color: var(--reai-text-muted);
  text-align: center;
}
.msg {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.msg.user {
  flex-direction: row-reverse;
}
.bubble {
  max-width: 70%;
  padding: 10px 14px;
  margin: 0;
  font-size: 14px;
  background: var(--reai-bubble-agent);
  border-radius: 12px;
}
.msg.user .bubble {
  color: var(--reai-nav-active);
  background: var(--reai-bubble-user);
}
.text {
  margin: 0;
  line-height: 1.5;
}
.bubble.voice {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--reai-nav-active);
}
.play {
  width: 24px;
  height: 24px;
  color: var(--reai-nav-active);
  cursor: pointer;
  background: none;
  border: 1px solid currentcolor;
  border-radius: 50%;
}
.wave {
  display: inline-block;
  width: 120px;
  height: 24px;
  background: var(--reai-accent);
  border-radius: 6px;
  opacity: 0.75;
}
.wave i {
  display: block;
  width: 40%;
  height: 100%;
  background: var(--reai-nav-active);
  border-radius: 6px;
  opacity: 0.6;
}
.vmeta {
  font-size: 11px;
}
.quicks {
  display: flex;
  gap: 8px;
  padding: 10px 0;
}
.quick {
  padding: 4px 10px;
  font-size: 12px;
  color: var(--reai-accent);
  cursor: pointer;
  background: var(--reai-card-2);
  border: none;
  border-radius: 999px;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.grow {
  flex: 1;
}
@media (width <= 1024px) {
  .workbench {
    flex-direction: column;
    overflow-y: auto;
  }
  .queue {
    flex: none;
    width: 100%;
  }
  .chat {
    min-height: 60vh;
  }
}
</style>
