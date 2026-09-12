<template>
  <div class="page">
    <h2>登录</h2>
    <AiInput v-model="username" placeholder="用户名（演示 demo）" />
    <AiInput v-model="password" type="password" placeholder="密码" show-password />
    <AiButton :loading="loading" @click="submit">登录</AiButton>
  </div>
</template>

<script setup lang="ts">
// 真实登录：POST /auth/login → 存 reai_token → 跳 /chat；失败 ElMessage（对齐 API 规范 §4.1）
import { ElMessage } from 'element-plus';
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const username = ref('demo');
const password = ref('');
const loading = ref(false);
const router = useRouter();

const submit = async (): Promise<void> => {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码');
    return;
  }
  loading.value = true;
  try {
    const data = await api.login(username.value, password.value);
    sessionStorage.setItem('reai_token', data.token);
    ElMessage.success(`欢迎回来，${data.user.name}`);
    await router.push('/chat');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登录失败');
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 360px;
  padding: 48px 16px;
  margin: 0 auto;
}
</style>
