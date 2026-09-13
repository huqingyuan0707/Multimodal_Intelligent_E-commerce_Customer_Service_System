// 按钮级权限指令（路由 meta.roles 管页面，本指令管按钮；对齐页面设计 §6）
// 用法：v-permission="'admin'" 或 v-permission="['shop','ops','admin']"
// 身份未取到时放行（宽松，避免闪删）；身份明确但缺权限则移除节点。
import type { Directive } from 'vue';
import { useUserStore } from '@/stores/user';

export const hasPerm = (need: string | string[] | undefined): boolean => {
  if (!need || (Array.isArray(need) && need.length === 0)) {
    return true;
  }
  const store = useUserStore();
  const mine = [...store.roles, ...store.perms];
  if (mine.length === 0) {
    return true;
  }
  const wants = Array.isArray(need) ? need : [need];
  return wants.some((r) => mine.includes(r));
};

export const vPermission: Directive<HTMLElement, string | string[]> = {
  mounted: (el, binding) => {
    if (!hasPerm(binding.value)) {
      el.remove();
    }
  },
};
