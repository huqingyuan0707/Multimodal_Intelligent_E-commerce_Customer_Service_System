<template>
  <div class="chat-panel">
    <StreamMessage content="对话框架已就绪，流式后续接入。" />
  </div>
</template>

<script setup lang="ts">
// 对话容器框架（虚拟列表/增量渲染后续补，见页面设计 §3.1）
import StreamMessage from './StreamMessage.vue';
</script>

<style scoped>
.chat-panel {
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  padding: 12px;
  background: var(--reai-card);
  box-shadow: var(--reai-shadow-card);
}
</style>
