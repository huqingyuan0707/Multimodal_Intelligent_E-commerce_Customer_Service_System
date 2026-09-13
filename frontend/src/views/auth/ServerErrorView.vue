<template>
  <div class="error-page">
    <div class="card">
      <p class="code">500</p>
      <h2 class="title">服务开小差了</h2>
      <p class="desc">系统异常，请稍后重试或联系管理员，并提供下方 trace_id。</p>
      <p class="trace">trace_id：{{ traceId }}</p>
      <AiButton class="back" @click="goHome">返回首页</AiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
// 500 服务异常（插画字 + 返回 + 报 trace_id，对齐页面设计 §3.9）
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AiButton from '@/shared/components/AiButton.vue';

const route = useRoute();
const router = useRouter();
const traceId = ref((route.query.trace_id as string | undefined) ?? `t-${Date.now().toString(36)}`);

const goHome = (): void => {
  void router.push('/chat');
};
</script>

<style scoped>
.error-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--reai-page-gradient);
}

.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  width: min(360px, 100%);
  padding: 40px 28px;
  text-align: center;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 16px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}

.code {
  margin: 0;
  font-size: 64px;
  font-weight: 800;
  line-height: 1;
  background: var(--reai-gradient);
  background-clip: text;
  color: transparent;
}

.title {
  margin: 0;
  font-size: 20px;
  color: var(--reai-text-main);
}

.desc {
  margin: 0;
  font-size: 14px;
  color: var(--reai-text-muted);
}

.trace {
  margin: 0;
  font-family: monospace;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.back {
  width: 100%;
  margin-top: 8px;
}
</style>
