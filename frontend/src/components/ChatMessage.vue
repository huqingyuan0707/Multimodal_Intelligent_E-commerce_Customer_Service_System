/**
 * 单条对话气泡（职责：用户/Agent 泡 + 图片/检测卡/引用/trace/追问 chips 渲染）
 * 链路：ChatView 消息列表 v-for → 预览/转人工/追问事件回抛页面层处理
 * 对齐：页面设计.md §3.1 StreamMessage/CitationList + design.pen 对话助手画板
 */
<template>
  <div class="bubble" :class="message.role">
    <div v-if="message.images?.length" class="thumbs">
      <img
        v-for="(u, i) in message.images"
        :key="`${message.id}-${i}`"
        :src="u"
        alt="售后图片"
        @click="preview(u)"
      />
    </div>
    <p class="content">{{ message.content }}</p>
    <VisionResultCard v-if="message.vision?.length" :inspections="message.vision" />
    <p v-if="message.need_human" class="human">
      置信不足已转人工复核，坐席将在 30 秒内接管
      <AiButton @click="transfer">立即转人工</AiButton>
    </p>
    <p v-if="message.references?.length" class="refs">
      引用：
      <span v-for="r in message.references" :key="r.source">[{{ r.title }}]</span>
    </p>
    <p v-if="message.trace_id" class="trace">trace: {{ message.trace_id }}</p>
    <p v-if="message.context" class="trace">
      上下文 {{ message.context.rounds }} 轮/约 {{ message.context.tokens }} token{{
        message.context.summarized ? '（已摘要）' : ''
      }}
    </p>
    <ChatSuggestions
      v-if="showFollowups"
      :empty="false"
      :welcome="[]"
      :followups="message.followups ?? []"
      @ask="ask"
    />
  </div>
</template>

<script setup lang="ts">
import AiButton from '@/shared/components/AiButton.vue';
import ChatSuggestions from './ChatSuggestions.vue';
import VisionResultCard from './VisionResultCard.vue';
import type { AgentMessage } from '@/types/agent';

defineProps<{
  message: AgentMessage;
  showFollowups: boolean;
}>();

const emit = defineEmits(['ask', 'preview', 'transfer']);

// 气泡内三个动作统一回抛（预览图 / 转人工 / 追问发送，发送链路仍归页面）
const preview = (url: string) => {
  emit('preview', url);
};

const transfer = () => {
  emit('transfer');
};

const ask = (text: string) => {
  emit('ask', text);
};
</script>

<style scoped>
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

/* AI 长答复（RAG 分点/降级摘要）保留原文换行，长单号/链接不断布局 */
.content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
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

.thumbs img {
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
</style>
