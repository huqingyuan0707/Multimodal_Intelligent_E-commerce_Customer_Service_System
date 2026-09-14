<template>
  <div class="msgs">
    <p v-if="phaseText" class="phase">{{ phaseText }}</p>
    <template v-for="m in messages" :key="m.id">
      <div class="msg" :class="m.role">
        <template v-if="m.role === 'agent'">
          <span class="avatar agent">AI</span>
          <div class="bubble">
            <p class="text">{{ m.content || '思考中…' }}</p>
            <VisionResultCard :inspections="m.vision ?? []" />
            <CitationList :refs="m.references ?? []" :trace-id="m.trace_id" @open="emit('open-doc', $event)" />
          </div>
        </template>
        <template v-else>
          <div v-if="m.modality === 'voice'" class="bubble voice">
            <button class="play" :aria-label="`播放语音 ${m.id}`" @click="emit('play-voice', m.id)">▶</button>
            <span class="wave"><i /></span>
            <span class="vmeta">{{ voiceText(m.id) }}</span>
          </div>
          <p v-else class="bubble user">{{ m.content }}</p>
          <span class="avatar">{{ name.charAt(0) || '客' }}</span>
        </template>
      </div>
      <!-- 工具透明展示：编排真调的工具 + 中文说明（画板 wtk00/wtk10），挂在对应 Agent 消息行下方 -->
      <ToolCallCard v-if="m.role === 'agent'" :calls="m.tool_calls ?? []" :notes="m.notes ?? []" />
    </template>
    <el-empty v-if="!messages.length && !streaming" description="本会话暂无消息" :image-size="56" />
  </div>

  <div class="quicks">
    <button
      v-for="q in QUICK_REPLIES"
      :key="q.key"
      class="quick"
      type="button"
      :disabled="locked && q.key === 'handoff'"
      @click="emit('quick', q.key)"
    >
      {{ q.label }}
    </button>
  </div>

  <p v-if="locked" class="locked">{{ lockedHint }}</p>
  <div class="input-row">
    <AiButton aria-label="上传图片" :disabled="locked" @click="emit('image')">图片</AiButton>
    <AiButton aria-label="语音输入" :disabled="locked" @click="emit('voice')">语音</AiButton>
    <AiInput
      :model-value="draft"
      class="grow"
      :disabled="locked"
      :placeholder="locked ? lockedHint : sendHint"
      @update:model-value="emit('update:draft', $event)"
      @keyup.enter="emit('send')"
    />
    <AiButton type="primary" :loading="streaming" :disabled="locked" @click="emit('send')">
      {{ sendLabel }}
    </AiButton>
  </div>
</template>

<script setup lang="ts">
// 坐席工作台中栏会话流：消息（VLM 蓝卡 / 引用金卡 / 语音行）+ 快捷话术 + 输入行
// 只做展示与事件，发送语义（坐席代回 / AI 代答 / 只读围观）由 WorkbenchView 按会话流转态决定
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import CitationList from '@/components/CitationList.vue';
import ToolCallCard from '@/components/ToolCallCard.vue';
import VisionResultCard from '@/components/VisionResultCard.vue';
import type { AgentMessage } from '@/types/agent';

defineProps<{
  name: string;
  messages: AgentMessage[];
  streaming: boolean;
  phaseText: string;
  draft: string;
  locked: boolean;
  lockedHint: string;
  sendHint: string;
  sendLabel: string;
}>();

const emit = defineEmits([
  'update:draft',
  'send',
  'quick',
  'image',
  'voice',
  'play-voice',
  'open-doc',
]);

// 快捷话术：转人工是动作，其余是话术填入
const QUICK_REPLIES = [
  { key: 'logistics', label: '查物流' },
  { key: 'refund', label: '退换货' },
  { key: 'handoff', label: '转人工' },
] as const;

// 语音演示元数据（时长·转写置信度；真语音链路接通后随消息下发）
const VOICE_META = { 'v-1': '0:12 · 转写0.91' } as const;

const voiceText = (id: string) => (id in VOICE_META ? VOICE_META[id as keyof typeof VOICE_META] : '');
</script>

<style scoped>
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
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-soft);
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
.bubble {
  max-width: 70%;
  padding: 10px 14px;
  margin: 0;
  font-size: var(--reai-fs-body);
  /* 缺 color 会白上白糊，显式深字 */
  color: var(--reai-text-on-light);
  background: var(--reai-bubble-agent);
  border-radius: 12px;
}
.msg.user .bubble {
  font-weight: var(--reai-fw-medium);
  color: var(--reai-nav-active);
  background: var(--reai-bubble-user);
}
.text {
  margin: 0;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
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
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-micro);
}
.quicks {
  display: flex;
  gap: 8px;
  padding: 10px 0;
}
.quick {
  padding: 4px 10px;
  font-size: var(--reai-fs-caption);
  font-weight: var(--reai-fw-medium);
  color: var(--reai-accent);
  cursor: pointer;
  background: var(--reai-card-2);
  border: none;
  border-radius: 999px;
}
.quick:hover:not(:disabled),
.quick:focus-visible:not(:disabled) {
  color: var(--reai-nav-active);
  background: var(--reai-primary);
}
.quick:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
/* 原生 button 不继承 Element Plus 焦点环，显式给键盘焦点 */
.quick:focus-visible,
.play:focus-visible {
  outline: 2px solid var(--reai-accent);
  outline-offset: 2px;
}
.play:hover {
  background: var(--reai-glass-border);
}
.locked {
  margin: 0 0 8px;
  font-size: var(--reai-fs-caption);
  color: var(--reai-notice);
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.grow {
  flex: 1;
}
</style>
