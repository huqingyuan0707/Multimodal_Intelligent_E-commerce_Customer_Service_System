<template>
  <router-view />
</template>

<script setup lang="ts">
// 根组件只做路由出口，系统壳由 AppLayout 提供（对齐页面设计 §2）
</script>

<style scoped>
:host {
  display: block;
}
</style>
