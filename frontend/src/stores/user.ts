// 用户 store（登录态唯一来源：顶栏展示 + 菜单/路由按角色过滤，对齐页面设计 §2）
// token 存 sessionStorage.reai_token（与 api 层同一口径）；401 一律走中央 handle401，页面不自行跳转。
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { loginApi, logoutApi, meApi } from '@/api';
import type { AppUser } from '@/types/user';

export type { AppUser };

const TOKEN_KEY = 'reai_token';

export const useUserStore = defineStore('user', () => {
  const user = ref<AppUser | null>(null);

  const roles = computed(() => user.value?.roles ?? []);
  const perms = computed(() => user.value?.perms ?? user.value?.roles ?? []);

  const hasToken = () => Boolean(sessionStorage.getItem(TOKEN_KEY));

  const clearLocal = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    user.value = null;
  };

  /** 登录：调接口成功后写 token 并回填身份；失败抛错由页面提示 */
  const login = async (username: string, password: string) => {
    const data = await loginApi({ username, password });
    sessionStorage.setItem(TOKEN_KEY, data.token);
    user.value = data.user;
    return data.user;
  };

  /** 登出：先通知服务端确认身份，无论成败都清本地态（JWT 无状态） */
  const logout = async () => {
    await logoutApi().catch(() => undefined);
    clearLocal();
  };

  /** 刷新页面后凭 token 恢复身份；返回是否拿到身份（false 交由路由守卫回登录页） */
  const loadMe = async () => {
    if (!hasToken()) {
      user.value = null;
      return false;
    }
    try {
      user.value = await meApi();
      return true;
    } catch {
      user.value = null;
      return false;
    }
  };

  const setUser = (u: AppUser) => {
    user.value = u;
  };

  const clearUser = () => {
    user.value = null;
  };

  return { user, roles, perms, hasToken, login, logout, loadMe, setUser, clearUser };
});
