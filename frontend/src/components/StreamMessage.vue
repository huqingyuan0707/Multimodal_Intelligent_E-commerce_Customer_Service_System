<template>
  <div class="msg">{{ content }}</div>
</template>

<script setup lang="ts">
// 流式消息占位（按 phase/message/done 分支渲染后续补）
defineProps<{
  content: string;
}>();
</script>

<style scoped>
.msg {
  color: var(--reai-text-main);
}
</style>
