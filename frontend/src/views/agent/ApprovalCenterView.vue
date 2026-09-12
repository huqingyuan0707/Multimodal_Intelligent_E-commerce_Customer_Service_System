<template>
  <div class="page">
    <h2>审批中心</h2>
    <ApprovalCard action="演示审批" />
  </div>
</template>

<script setup lang="ts">
// 审批中心框架（见页面设计 §3.4，具体批驳后续补）
import ApprovalCard from '@/components/ApprovalCard.vue';
</script>

<style scoped>
.page {
  padding: 16px;
}
</style>
