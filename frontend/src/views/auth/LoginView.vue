<template>
  <div class="login">
    <div class="brand">
      <svg class="hero" viewBox="0 56 340 213" aria-hidden="true">
        <defs>
          <linearGradient id="cloud-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="var(--reai-primary)" />
            <stop offset="1" stop-color="var(--reai-purple)" />
          </linearGradient>
        </defs>
        <ellipse
          cx="170"
          cy="252"
          rx="132"
          ry="16"
          fill="none"
          stroke="var(--reai-border)"
          stroke-dasharray="4 5"
        />
        <polygon
          points="170,196 268,224 170,252 72,224"
          fill="var(--reai-card-2)"
          stroke="var(--reai-primary)"
          stroke-width="1.5"
          opacity="0.9"
        />
        <polygon
          points="170,210 240,228 170,246 100,228"
          fill="none"
          stroke="var(--reai-accent)"
          stroke-width="1"
          opacity="0.6"
        />
        <line
          x1="120"
          y1="210"
          x2="66"
          y2="132"
          stroke="var(--reai-accent)"
          stroke-width="1.5"
          stroke-dasharray="4 3"
          opacity="0.4"
        />
        <line
          x1="110"
          y1="232"
          x2="72"
          y2="212"
          stroke="var(--reai-accent)"
          stroke-width="1.5"
          stroke-dasharray="4 3"
          opacity="0.4"
        />
        <line
          x1="170"
          y1="196"
          x2="270"
          y2="150"
          stroke="var(--reai-accent)"
          stroke-width="1.5"
          stroke-dasharray="4 3"
          opacity="0.4"
        />
        <circle
          cx="52"
          cy="110"
          r="24"
          fill="var(--reai-card-2)"
          stroke="var(--reai-primary)"
          stroke-width="2"
        />
        <circle cx="52" cy="103" r="7" fill="var(--reai-accent)" />
        <path
          d="M 41 122 Q 52 111 63 122"
          fill="none"
          stroke="var(--reai-accent)"
          stroke-width="2"
          stroke-linecap="round"
        />
        <circle
          cx="64"
          cy="196"
          r="19"
          fill="var(--reai-card-2)"
          stroke="var(--reai-primary)"
          stroke-width="2"
        />
        <circle cx="64" cy="190" r="6" fill="var(--reai-accent)" />
        <path
          d="M 55 206 Q 64 197 73 206"
          fill="none"
          stroke="var(--reai-accent)"
          stroke-width="2"
          stroke-linecap="round"
        />
        <circle cx="138" cy="148" r="26" fill="url(#cloud-grad)" />
        <circle cx="168" cy="132" r="34" fill="url(#cloud-grad)" />
        <circle cx="198" cy="148" r="26" fill="url(#cloud-grad)" />
        <rect x="138" y="148" width="86" height="28" rx="14" fill="url(#cloud-grad)" />
        <rect
          x="150"
          y="156"
          width="44"
          height="7"
          rx="3.5"
          fill="var(--reai-nav-active)"
          opacity="0.85"
        />
        <rect
          x="150"
          y="168"
          width="30"
          height="7"
          rx="3.5"
          fill="var(--reai-nav-active)"
          opacity="0.6"
        />
        <rect
          x="256"
          y="96"
          width="58"
          height="58"
          rx="14"
          fill="var(--reai-card-2)"
          stroke="var(--reai-accent)"
          stroke-width="2"
        />
        <text
          x="285"
          y="133"
          text-anchor="middle"
          font-size="22"
          font-weight="700"
          fill="var(--reai-accent)"
        >
          AI
        </text>
        <circle cx="300" cy="60" r="2.5" fill="var(--reai-accent)" opacity="0.5" />
        <circle cx="30" cy="180" r="2" fill="var(--reai-accent)" opacity="0.5" />
        <circle cx="240" cy="70" r="2" fill="var(--reai-accent)" opacity="0.5" />
      </svg>
      <h1 class="title">智能客服系统</h1>
      <p class="subtitle">多模态会话平台</p>
      <div class="points">
        <span class="chip">安全认证</span>
        <span class="chip">权限管控</span>
        <span class="chip">会话追踪</span>
      </div>
    </div>
    <div class="card">
      <h2 class="card-title">账号登录</h2>
      <AiInput v-model="username" placeholder="账号（演示 demo）" />
      <AiInput v-model="password" type="password" placeholder="密码" show-password />
      <AiInput v-model="tenant" placeholder="租户 ID（仅本地记住）" />
      <div class="row">
        <span />
        <el-button link size="small" class="link" @click="forgot">忘记密码</el-button>
      </div>
      <AiButton :loading="loading" class="submit" @click="submit">登录</AiButton>
      <p class="foot">安全认证 · 权限管控 · 会话追踪</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// 深色分屏登录：左品牌宣导 + 等距插画 + 右玻璃登录卡；账密走 request，租户 ID 仅本地记住（对齐页面设计 §3.9）
import { ElButton, ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { loginApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const username = ref('admin');
const password = ref('');
const tenant = ref('');
const loading = ref(false);
const router = useRouter();

onMounted(() => {
  tenant.value = sessionStorage.getItem('reai_tenant') ?? '';
});

const forgot = () => {
  ElMessage.info('请联系管理员重置密码（演示占位）');
};

const submit = async () => {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码');
    return;
  }
  loading.value = true;
  try {
    const data = await loginApi({ username: username.value, password: password.value });
    sessionStorage.setItem('reai_token', data.token);
    sessionStorage.setItem('reai_tenant', tenant.value.trim());
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
/* 左右两列等高：Grid 行高取两列内容较大者，卡片拉伸到与左品牌块同高，
   顶边/底边齐平；整组用 align-content 垂直居中（行不参与填充容器，卡片不会被拉满屏） */
.login {
  display: grid;
  grid-template-columns: minmax(0, 340px) minmax(0, 360px);
  gap: 64px;
  align-items: stretch;
  place-content: center;
  box-sizing: border-box;
  min-height: 100vh;
  padding: 24px;
  background: var(--reai-page-gradient);
}

/* <768 单列：品牌区隐藏，登录卡占满（对齐页面设计 §5） */
@media (width <= 768px) {
  .login {
    grid-template-columns: minmax(0, 400px);
    gap: 0;
  }

  .brand {
    display: none;
  }
}

.brand {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.hero {
  width: 100%;
  max-width: 340px;
  height: auto;
}

.title {
  margin: 8px 0 0;
  font-size: 44px;
  color: var(--reai-text-main);
  letter-spacing: 4px;
}

.subtitle {
  margin: 12px 0 24px;
  font-size: 18px;
  color: var(--reai-text-muted);
  letter-spacing: 8px;
}

.points {
  display: flex;
  gap: 12px;
}

.chip {
  padding: 6px 14px;
  font-size: 13px;
  color: var(--reai-accent);
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 999px;
  backdrop-filter: blur(12px);
}

.card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
  width: min(360px, 100%);
  padding: 32px 28px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 16px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);

  --el-input-border-radius: 12px;
  --el-input-border-color: transparent;
  --el-input-focus-border-color: var(--reai-accent);
  --el-input-bg-color: var(--reai-card-2);
}

.card-title {
  margin: 0 0 8px;
  font-size: 20px;
  text-align: center;
  color: var(--reai-text-main);
}

.row {
  display: flex;
  justify-content: space-between;
}

.link {
  --el-button-text-color: var(--reai-text-muted);
  --el-button-hover-text-color: var(--reai-accent);
}

.submit {
  width: 100%;
  padding: 12px;
  font-size: 16px;
  background: var(--reai-gradient);
  border: none;
  border-radius: 12px;
  color: var(--reai-nav-active);
}

.foot {
  margin: 4px 0 0;
  font-size: 12px;
  text-align: center;
  color: var(--reai-text-muted);
}

@media (width <= 960px) {
  .login {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    gap: 32px;
  }

  .hero {
    display: none;
  }
}
</style>
