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
        <el-dropdown trigger="click" placement="bottom-end" @command="handleUserCommand">
          <span class="username dropdown-trigger"
            >{{ user?.name ?? '管理员' }}<i class="caret"
          /></span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <div class="who">
                  <span class="who-name">{{ user?.name ?? '' }}</span>
                  <span class="who-tenant">{{ user?.tenant ?? '' }}</span>
                </div>
                <div class="who-roles" :title="(user?.roles ?? []).join(',')">
                  <el-tag v-for="r in displayRoles" :key="r" size="small">{{ r }}</el-tag>
                  <span v-if="extraPermCount > 0" class="more">+{{ extraPermCount }}</span>
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="switch" divided>切换用户</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
    <UserSwitchDialog v-model="showSwitch" @switched="onSwitched" />
  </el-container>
</template>

<script setup lang="ts">
// 系统壳：蓝紫渐变顶栏（品牌+顶部 Tab 导航+坐席状态/通知/用户下拉+切换用户）+ 主区（对齐页面设计 §2）
import {
  ElButton,
  ElContainer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElHeader,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElMessage,
  ElMessageBox,
  ElTag,
} from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import UserSwitchDialog from '@/components/UserSwitchDialog.vue';
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

const hasPerm = (roles: unknown) => {
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

// 下拉身份行只展示域角色（cs/kb/shop…，最多 3 个），权限令牌（xx:yy）折进 +N，悬停看全量
const displayRoles = computed(() =>
  (user.value?.roles ?? []).filter(r => !r.includes(':')).slice(0, 3),
);
const extraPermCount = computed(() =>
  Math.max(0, (user.value?.roles ?? []).length - displayRoles.value.length),
);

const showNotice = () => {
  ElMessage.info('暂无新消息（演示占位，通知中心后续补）');
};

const logout = async () => {
  // 走 store：先让服务端确认身份，再清本地态（JWT 无状态，失败也不卡在登录态）
  await userStore.logout();
  ElMessage.success('已退出登录');
  router.push('/login');
};

const showSwitch = ref(false);

// 顶栏用户下拉：切换用户（admin 弹窗代入，普通用户退出后去登录页重登）/ 退出登录
const handleUserCommand = async (command: string) => {
  if (command === 'logout') {
    await logout();
    return;
  }
  if (command !== 'switch') {
    return;
  }
  if (!userStore.isAdmin) {
    try {
      await ElMessageBox.confirm(
        '当前账号无代入权限，将退出并前往登录页用新账号登录，是否继续？',
        '切换用户',
      );
    } catch {
      return; // 用户取消
    }
    await userStore.logout();
    router.push({ path: '/login', query: { redirect: route.fullPath } });
    return;
  }
  showSwitch.value = true;
};

// 代入成功：token 已换，整页重载让守卫重取身份、各页重拉（新身份无权看当前页时守卫踢回 /chat）
const onSwitched = () => {
  router.go(0);
};

onMounted(() => {
  if (!userStore.user) {
    userStore.loadMe();
  }
});
</script>

<style scoped>
.layout {
  height: 100vh;
  min-width: 0;
}

.topbar {
  display: flex;
  gap: 24px;
  align-items: center;
  min-width: 0;
  background: var(--reai-gradient);
}

.brand {
  font-size: 17px;
  font-weight: var(--reai-fw-bold);
  line-height: var(--reai-lh-tight);
  letter-spacing: 0.02em;
  color: var(--reai-nav-active);
  white-space: nowrap;
}

.tabs {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  font-size: var(--reai-fs-body);
  font-weight: var(--reai-fw-medium);
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
  font-size: var(--reai-fs-body-sm);
  font-weight: var(--reai-fw-medium);
  line-height: var(--reai-lh-tight);
  color: var(--reai-nav-active);
  white-space: nowrap;
}

.online {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

/* EP 组件自带字号（dropdown/button 14px、tag 12px）与 .status 13px 混排会大小不一、基线错位，统一为 13px */
.status :deep(.el-dropdown),
.status :deep(.el-button),
.status :deep(.el-tag) {
  font-size: 13px;
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
  display: inline-flex;
  gap: 6px;
  align-items: center;
  height: auto;
  padding: 0;

  --el-button-text-color: var(--reai-nav-active);
  --el-button-hover-text-color: var(--reai-nav-active);
}

.tenant,
.username {
  display: inline-flex;
  align-items: center;
  font-weight: var(--reai-fw-medium);
  color: var(--reai-nav-text);
}

.who {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.who-name {
  font-weight: 600;
}

.who-tenant {
  font-size: 12px;
  opacity: 0.7;
}

.who-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  max-width: 240px;
  margin-top: 4px;
}

.more {
  font-size: 12px;
  opacity: 0.7;
}

.dropdown-trigger {
  cursor: pointer;
  outline: none;
}

.caret {
  display: inline-block;
  width: 0;
  height: 0;
  margin-left: 4px;
  vertical-align: middle;
  border-top: 5px solid var(--reai-nav-text);
  border-right: 4px solid transparent;
  border-left: 4px solid transparent;
}

.main {
  height: calc(100vh - 60px);
  min-width: 0;
  padding: 16px;
  overflow-y: auto;
  background: var(--reai-bg);
}

/* <768 单列：顶栏收紧，次要状态隐藏，菜单横滑 */
@media (width <= 768px) {
  .topbar {
    gap: 12px;
  }

  .brand {
    font-size: 15px;
  }

  .tenant,
  .online {
    display: none;
  }
}
</style>
