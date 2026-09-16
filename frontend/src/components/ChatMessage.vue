<!-- 单条对话气泡（职责：用户/Agent 泡 + 图片/检测卡/引用溯源/赞踩反馈/trace/追问 chips 渲染）
     链路：ChatView 消息列表 v-for → 预览/转人工/追问/引用/赞踩/重试事件回抛页面层处理
     对齐：页面设计.md §3.1 + design.pen 对话助手画板 -->
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
      <span
        v-for="r in message.references"
        :key="r.source"
        class="cite"
        role="button"
        tabindex="0"
        @click="openDoc(r.source)"
        @keyup.enter="openDoc(r.source)"
        >[{{ r.title }}]</span
      >
    </p>
    <p v-if="message.trace_id" class="trace">trace: {{ message.trace_id }}</p>
    <p v-if="message.context" class="trace">
      上下文 {{ message.context.rounds }} 轮/约 {{ message.context.tokens }} token{{
        message.context.summarized ? '（已摘要）' : ''
      }}
    </p>
    <!-- 赞踩反馈（差评进 Mining 待补知识）：仅真后端回复行（带 message_id）显示；提交后置灰 -->
    <p v-if="message.role === 'agent' && message.message_id" class="feedback">
      <button
        class="fb"
        :class="{ on: message.feedback === 'up', off: !!message.feedback }"
        :disabled="!!message.feedback"
        aria-label="回答有帮助"
        @click="vote('up')"
      >
        👍 有用
      </button>
      <button
        class="fb"
        :class="{ on: message.feedback === 'down', off: !!message.feedback }"
        :disabled="!!message.feedback"
        aria-label="回答没帮助"
        @click="vote('down')"
      >
        👎 不准
      </button>
      <span v-if="message.feedback" class="fb-done">
        {{ message.feedback === 'up' ? '感谢反馈' : '已记入待改进，将安排人工复核' }}
      </span>
    </p>
    <!-- 错误气泡：友好话术 + 重试 + 转人工（对齐页面设计 §3.1 状态完整性） -->
    <p v-if="message.retryable" class="human">
      <AiButton @click="retry">重试</AiButton>
      <AiButton @click="transfer">转人工</AiButton>
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

const emit = defineEmits(['ask', 'preview', 'transfer', 'vote', 'open-doc', 'retry']);

// 气泡内动作统一回抛（预览图 / 转人工 / 追问发送 / 赞踩 / 引用原文 / 重试，链路与状态归页面）
const preview = (url: string) => {
  emit('preview', url);
};

const transfer = () => {
  emit('transfer');
};

const ask = (text: string) => {
  emit('ask', text);
};

const vote = (v: 'up' | 'down') => {
  emit('vote', v);
};

const openDoc = (source: string) => {
  emit('open-doc', source);
};

const retry = () => {
  emit('retry');
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
  color: var(--reai-text-on-brand);
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

/* 引用角标可点跳原文（对齐 CitationList 同口径） */
.cite {
  cursor: pointer;
}

.cite:hover {
  text-decoration: underline;
}

.feedback {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 4px 0 0;
}

.fb {
  padding: 2px 10px;
  font-size: 12px;
  color: var(--reai-text-muted);
  cursor: pointer;
  background: none;
  border: 1px solid var(--reai-border);
  border-radius: 12px;
}

.fb:disabled {
  cursor: default;
}

.fb:hover:not(:disabled) {
  color: var(--reai-primary);
  border-color: var(--reai-primary);
}

.fb.on {
  color: var(--reai-primary);
  border-color: var(--reai-primary);
}

.fb-done {
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
