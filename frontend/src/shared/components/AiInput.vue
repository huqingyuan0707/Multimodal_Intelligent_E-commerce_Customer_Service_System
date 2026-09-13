<template>
  <el-input
    class="ai-input"
    :model-value="modelValue"
    :placeholder="placeholder"
    v-bind="$attrs"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
// 业务输入优先用 AiInput 而非裸 el-input（对齐前端 Skill §5），支持 v-model 双向绑定
defineProps<{
  modelValue?: string;
  placeholder?: string;
}>();

const emit = defineEmits(['update:modelValue']);
</script>

<style scoped>
.ai-input {
  width: 100%;
}
</style>
