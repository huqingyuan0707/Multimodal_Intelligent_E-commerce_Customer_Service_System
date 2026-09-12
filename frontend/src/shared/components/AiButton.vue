<template>
  <el-button class="ai-button" :loading="loading" v-bind="$attrs">
    <slot />
  </el-button>
</template>

<script setup lang="ts">
// 业务按钮优先用 AiButton而非裸 el-button（对齐前端 Skill §5），具体主题后续补
defineProps<{
  loading?: boolean;
}>();
</script>

<style scoped>
.ai-button {
  border-color: var(--reai-border);
}
</style>
