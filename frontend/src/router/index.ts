// 路由表（AppLayout 嵌套 + 懒加载 + meta.title/roles，对齐页面设计 §1）
// 守卫两件事：登录态（无 token / 身份取不到 → /login）+ 角色（meta.roles 不匹配 → 回 /chat 并提示）
import { ElMessage } from 'element-plus';
import type { RouteRecordRaw } from 'vue-router';
import { createRouter, createWebHistory } from 'vue-router';
import AppLayout from '@/components/AppLayout.vue';
import { useUserStore } from '@/stores/user';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: () => import('@/views/auth/LoginView.vue'),
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/chat',
    children: [
      {
        path: 'chat',
        component: () => import('@/views/agent/ChatView.vue'),
        meta: { title: '对话助手', roles: ['buyer', 'cs', 'ops', 'admin'] },
      },
      {
        path: 'workbench',
        component: () => import('@/views/workbench/WorkbenchView.vue'),
        meta: { title: '坐席工作台', roles: ['cs', 'admin'] },
      },
      {
        path: 'tasks',
        component: () => import('@/views/agent/TaskCenterView.vue'),
        meta: { title: '任务中心', roles: ['cs', 'ops', 'admin'] },
      },
      {
        path: 'approvals',
        component: () => import('@/views/agent/ApprovalCenterView.vue'),
        meta: { title: '审批中心', roles: ['cs', 'admin'] },
      },
      {
        path: 'knowledge',
        component: () => import('@/views/knowledge/KnowledgeView.vue'),
        meta: { title: '知识库', roles: ['ops', 'admin'] },
      },
      {
        path: 'studio',
        component: () => import('@/views/studio/StudioView.vue'),
        meta: { title: 'Agent Studio', roles: ['ops', 'admin'] },
      },
      {
        path: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '数据看板', roles: ['ops', 'admin'] },
      },
      {
        path: 'admin',
        component: () => import('@/views/admin/AdminView.vue'),
        meta: { title: '管理后台', roles: ['admin'] },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    component: () => import('@/views/auth/NotFoundView.vue'),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async to => {
  const userStore = useUserStore();

  if (to.path === '/login') {
    // 已登录不必再看登录页，直接进主区
    return userStore.hasToken() ? { path: '/chat' } : true;
  }
  if (!userStore.hasToken()) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }
  // 刷新页面后内存态为空：凭 token 拉一次身份；过期/伪造由中央 401 处理并回登录页
  if (!userStore.user && !(await userStore.loadMe())) {
    return { path: '/login' };
  }
  // 身份未取到时先放行（宽松），已取到则严格按 meta.roles 拦
  const need = to.meta.roles as string[] | undefined;
  if (need?.length && userStore.roles.length) {
    if (!need.some(r => userStore.roles.includes(r))) {
      ElMessage.error('当前角色无权访问该页面');
      return { path: '/chat' };
    }
  }
  return true;
});

export default router;
