<template>
  <el-container class="layout">
    <el-header class="topbar">
      <div class="brand">智能客服工作台</div>
      <el-menu :default-active="route.path" mode="horizontal" router class="tabs">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          {{ m.title }}
        </el-menu-item>
      </el-menu>
      <div class="status">
        <el-tag v-if="env !== 'production'" type="warning" size="small">{{ env }}</el-tag>
        <span class="online"><i class="dot online-dot" />坐席在线</span>
        <el-button link size="small" class="top-link" @click="showNotice">
          <i class="dot notice-dot" />消息通知
        </el-button>
        <span class="tenant">{{ user?.tenant ?? '演示租户' }}</span>
        <span class="username">{{ user?.name ?? '管理员' }}</span>
        <el-button link size="small" class="top-link" @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
// 系统壳：蓝紫渐变顶栏（品牌+顶部 Tab 导航+坐席状态/通知/用户/退出）+ 主区（对齐页面设计 §2）
import {
  ElButton,
  ElContainer,
  ElHeader,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElMessage,
  ElTag,
} from 'element-plus';
import { computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useUserStore } from '@/stores/user';

type MenuItem = {
  path: string;
  title: string;
};

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();
const user = computed(() => userStore.user);
const env = import.meta.env.MODE ?? 'development';

const hasPerm = (roles: unknown): boolean => {
  if (!Array.isArray(roles) || roles.length === 0) {
    return true;
  }
  const mine = userStore.roles;
  if (mine.length === 0) {
    return true; // 身份未取到时先全展示，接口就绪后按角色过滤
  }
  return (roles as string[]).some(r => mine.includes(r));
};

const menus = computed<MenuItem[]>(() =>
  router
    .getRoutes()
    .filter(r => typeof r.meta.title === 'string' && hasPerm(r.meta.roles))
    .map(r => ({ path: r.path, title: r.meta.title as string })),
);

const showNotice = (): void => {
  ElMessage.info('暂无新消息（演示占位，通知中心后续补）');
};

const logout = async (): Promise<void> => {
  // 走 store：先让服务端确认身份，再清本地态（JWT 无状态，失败也不卡在登录态）
  await userStore.logout();
  ElMessage.success('已退出登录');
  void router.push('/login');
};

onMounted(() => {
  if (!userStore.user) {
    void userStore.loadMe();
  }
});
</script>

<style scoped>
.layout {
  height: 100vh;
}

.topbar {
  display: flex;
  gap: 24px;
  align-items: center;
  background: var(--reai-gradient);
}

.brand {
  font-size: 17px;
  font-weight: 700;
  color: var(--reai-nav-active);
  white-space: nowrap;
}

.tabs {
  flex: 1;
  background: transparent;
  border-bottom: none;

  --el-menu-text-color: var(--reai-nav-text);
  --el-menu-active-color: var(--reai-nav-active);
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: var(--reai-nav-hover);
}

.status {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 13px;
  color: var(--reai-nav-active);
  white-space: nowrap;
}

.online {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.online-dot {
  background: var(--reai-online);
}

.notice-dot {
  background: var(--reai-notice);
}

.top-link {
  --el-button-text-color: var(--reai-nav-active);
  --el-button-hover-text-color: var(--reai-nav-active);
}

.tenant,
.username {
  color: var(--reai-nav-text);
}

.main {
  height: calc(100vh - 60px);
  padding: 16px;
  background: var(--reai-bg);
}
</style>
