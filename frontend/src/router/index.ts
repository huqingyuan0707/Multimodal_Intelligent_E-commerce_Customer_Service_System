// 路由表（懒加载+meta.roles，对齐页面设计 §1；守卫只做登录态，具体权限后续补）
import type { RouteRecordRaw } from 'vue-router';
import { createRouter, createWebHistory } from 'vue-router';

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/chat' },
  {
    path: '/login',
    component: () => import('@/views/auth/LoginView.vue'),
  },
  {
    path: '/chat',
    component: () => import('@/views/agent/ChatView.vue'),
    meta: { roles: ['buyer', 'cs', 'ops', 'admin'] },
  },
  {
    path: '/workbench',
    component: () => import('@/views/workbench/WorkbenchView.vue'),
    meta: { roles: ['cs', 'admin'] },
  },
  {
    path: '/tasks',
    component: () => import('@/views/agent/TaskCenterView.vue'),
    meta: { roles: ['cs', 'ops', 'admin'] },
  },
  {
    path: '/approvals',
    component: () => import('@/views/agent/ApprovalCenterView.vue'),
    meta: { roles: ['cs', 'admin'] },
  },
  {
    path: '/knowledge',
    component: () => import('@/views/knowledge/KnowledgeView.vue'),
    meta: { roles: ['ops', 'admin'] },
  },
  {
    path: '/studio',
    component: () => import('@/views/studio/StudioView.vue'),
    meta: { roles: ['ops', 'admin'] },
  },
  {
    path: '/dashboard',
    component: () => import('@/views/dashboard/DashboardView.vue'),
    meta: { roles: ['ops', 'admin'] },
  },
  {
    path: '/admin',
    component: () => import('@/views/admin/AdminView.vue'),
    meta: { roles: ['admin'] },
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

export default router;
