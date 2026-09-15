// 主题切换（浅色默认 / 深色可切，对齐 DESIGN.md §Colors + 页面设计 §2）
// 链路：localStorage('reai_theme') → <html> 的 .dark 类（Element Plus dark css-vars 认同一个类，天然联动）
// → tokens.css html.dark 覆盖块换肤；/screen 大屏由 AppLayout watcher 在其路由下临时锁深色。
// 模块级单例 ref：顶栏按钮与任何页面共享同一状态；storage/document 只在函数内触碰（node 测试可桩）。
import { ref } from 'vue';

const STORAGE_KEY = 'reai.theme';

export type ThemeName = 'light' | 'dark';

/** 当前主题（模块级共享；initTheme 前恒为浅色默认） */
export const theme = ref<ThemeName>('light');

const storedTheme = (): ThemeName =>
  typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'dark'
    ? 'dark'
    : 'light';

/** 把状态写到 <html>（EP 与 tokens 都靠 .dark 类） */
const applyTheme = () => {
  document.documentElement.classList.toggle('dark', theme.value === 'dark');
};

/** 切换浅色/深色并持久化 */
export const toggleTheme = () => {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  localStorage.setItem(STORAGE_KEY, theme.value);
  applyTheme();
};

/** 应用启动时调用一次：读偏好 + 首帧前落类，避免深色用户闪白 */
export const initTheme = () => {
  theme.value = storedTheme();
  applyTheme();
};
