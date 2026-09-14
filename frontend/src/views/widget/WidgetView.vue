<template>
  <div class="widget">
    <p class="brand">{{ shopName }} · 在线客服</p>
    <div class="list">
      <div v-for="m in messages" :key="m.id" class="bubble" :class="m.role">
        <p class="content">{{ m.content }}</p>
        <p v-if="m.references?.length" class="refs">
          <span v-for="r in m.references" :key="r.source">[{{ r.title }}]</span>
        </p>
      </div>
      <div v-if="streaming" class="bubble agent">
        <p class="content">{{ draft || '思考中…' }}</p>
      </div>
    </div>
    <div class="input-row">
      <AiInput v-model="input" placeholder="请输入问题" @keyup.enter="send" />
      <AiButton :loading="streaming" @click="send">发送</AiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
// 独立站嵌入版对话（/chat 精简：无 Trace/管理入口；tenant 取 ?tenant=；高度自适应，对齐页面设计 §3.9）
import { ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useAgentStream } from '@/composables/useAgentStream';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { AgentMessage } from '@/types/agent';

const route = useRoute();
const shopName = ref('店铺客服');
const messages = ref<AgentMessage[]>([]);
const input = ref('');
const { streaming, draft, error, start, toMessage } = useAgentStream();

onMounted(() => {
  const tenant = route.query.tenant;
  const name = Array.isArray(tenant) ? tenant[0] : tenant;
  if (typeof name === 'string' && name) {
    shopName.value = name;
    sessionStorage.setItem('reai_tenant', name);
  }
});

const send = async () => {
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
</script>

<style scoped>
.widget {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  padding: 12px;
  background: var(--reai-bg);
}

.brand {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--reai-text-main);
}

.list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
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

.content {
  margin: 0;
  font-size: 14px;
  /* 嵌入版与 ChatMessage 同口径：保留回答原文换行 */
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.refs {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.input-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
</style>
