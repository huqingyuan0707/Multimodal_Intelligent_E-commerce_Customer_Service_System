<template>
  <el-button :loading="loading" v-bind="$attrs">
    <slot />
  </el-button>
</template>

<script setup lang="ts">
// 业务按钮统一入口（对齐前端 Skill §5）：纯透传 el-button，外观即 Element Plus 标准
// （2026-09-16 用户指令：所有按钮按 EP 标准来，移除原 border-color 覆盖）。
// 主题定制只走 tokens.css 的 --el-* 变量归一，不在组件里写样式。
defineProps<{
  loading?: boolean;
}>();
</script>
