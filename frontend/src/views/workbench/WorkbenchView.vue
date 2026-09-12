<template>
  <div class="page">
    <h2>坐席工作台</h2>
    <p>三栏框架：队列｜对话+Trace｜客户+订单（后续补）。</p>
    <ChatPanel />
  </div>
</template>

<script setup lang="ts">
// 坐席工作台框架（见页面设计 §3.2）
import ChatPanel from '@/components/ChatPanel.vue';
</script>

<style scoped>
.page {
  padding: 16px;
}
</style>
