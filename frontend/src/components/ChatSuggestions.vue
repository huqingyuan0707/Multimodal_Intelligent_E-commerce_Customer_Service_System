/**
 * 对话建议组件（职责：空态欢迎卡 + 追问延伸 chips，点击直接发送）
 * 链路：ChatView 空态 / 最后一条 Agent 回复下 → ask 事件回 ChatView.sendPreset
 * 对齐：页面设计.md §3.1 状态空 + design.pen 对话助手-预设/追问画板
 */
<template>
  <div v-if="empty" class="welcome">
    <h3 class="welcome-title">你好，我是智能客服小助手</h3>
    <p class="welcome-desc">试试下面的预设问题，一键发送；回答后还可点追问继续深挖</p>
    <div class="chips">
      <AiButton v-for="q in welcome" :key="q" class="chip" @click="ask(q)">
        {{ q }}
      </AiButton>
    </div>
  </div>
  <div v-else-if="followups.length" class="followups">
    <p class="follow-title">猜你想问</p>
    <div class="chips">
      <AiButton v-for="f in followups" :key="f" class="chip" @click="ask(f)">
        {{ f }}
      </AiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import AiButton from '@/shared/components/AiButton.vue';

defineProps<{
  empty: boolean;
  welcome: string[];
  followups: string[];
}>();

const emit = defineEmits(['ask']);

// chips 点击回抛原文（页面层直接 sendPreset 发送，组件不碰发送链路）
const ask = (text: string) => {
  emit('ask', text);
};
</script>

<style scoped>
.welcome {
  padding: 20px 16px;
  background: var(--reai-card);
  border: 1px solid var(--reai-border);
  border-radius: 12px;
  box-shadow: var(--reai-shadow-card);
}

.welcome-title {
  margin: 0 0 4px;
  font-size: 16px;
  color: var(--reai-text-main);
}

.welcome-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--reai-text-muted);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  border-color: var(--reai-border);
}

.followups {
  padding: 8px;
  margin-top: 8px;
  background: var(--reai-primary-soft);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
}

.follow-title {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
