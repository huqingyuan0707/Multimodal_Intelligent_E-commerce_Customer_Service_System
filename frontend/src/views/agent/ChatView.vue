<template>
  <div class="page">
    <h2>对话助手</h2>
    <div class="list">
      <div v-for="m in messages" :key="m.id" class="bubble" :class="m.role">
        <p class="content">{{ m.content }}</p>
        <p v-if="m.references?.length" class="refs">
          引用：
          <span v-for="r in m.references" :key="r.doc_id">[{{ r.title }}]</span>
        </p>
        <p v-if="m.trace_id" class="trace">trace: {{ m.trace_id }}</p>
      </div>
      <div v-if="streaming" class="bubble agent">
        <p class="content">{{ draft || phase || '思考中…' }}</p>
      </div>
    </div>
    <div class="input-row">
      <AiInput v-model="input" placeholder="请输入问题，如：退货政策是什么" @keyup.enter="send" />
      <AiButton :loading="streaming" @click="send">发送</AiButton>
      <AiButton @click="transfer">转人工</AiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
// 真实对话：输入 → useAgentStream 流式 → 落条展示引用/trace（对齐页面设计 §3.1/§4）
import { ElMessage } from 'element-plus';
import { ref } from 'vue';
import { useAgentStream } from '@/composables/useAgentStream';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AgentMessage } from '@/types/agent';

const messages = ref<AgentMessage[]>([]);
const input = ref('');
const { streaming, phase, draft, error, start, toMessage } = useAgentStream();

const send = async (): Promise<void> => {
  const query = input.value.trim();
  if (!query || streaming.value) {
    return;
  }
  messages.value = [
    ...messages.value,
    { id: `u-${Date.now()}`, role: 'user', modality: 'text', content: query },
  ];
  input.value = '';
  await start(query);
  if (error.value) {
    ElMessage.error(error.value);
    return;
  }
  messages.value = [...messages.value, toMessage(`a-${Date.now()}`)];
};

const transfer = (): void => {
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
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 720px;
  padding: 16px;
  margin: 0 auto;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
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

.input-row {
  display: flex;
  gap: 8px;
}
</style>
