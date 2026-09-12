<template>
  <div class="card">
    <p>审批框架：{{ action }}</p>
  </div>
</template>

<script setup lang="ts">
// 审批卡占位（批/驳/改参后续补，破坏操作先 confirm）
defineProps<{
  action: string;
}>();
</script>

<style scoped>
.card {
  border: 1px solid var(--reai-border);
  border-radius: 8px;
  padding: 8px;
}
</style>
