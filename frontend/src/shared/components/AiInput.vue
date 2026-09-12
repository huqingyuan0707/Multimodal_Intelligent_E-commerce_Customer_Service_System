<template>
  <el-input class="ai-input" :placeholder="placeholder" v-bind="$attrs" />
</template>

<script setup lang="ts">
// 业务输入优先用 AiInput 而非裸 el-input（对齐前端 Skill §5），具体主题后续补
defineProps<{
  placeholder?: string;
}>();
</script>

<style scoped>
.ai-input {
  width: 100%;
}
</style>
