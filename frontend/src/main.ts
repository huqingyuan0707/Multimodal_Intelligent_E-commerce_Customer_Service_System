// 应用入口（只做装配：router+pinia+样式，对齐页面设计 §2）
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import 'element-plus/theme-chalk/dark/css-vars.css'; // 深色变量包：.dark 类挂上才生效（浅色默认）
import { createPinia } from 'pinia';
import { createApp } from 'vue';
import App from './App.vue';
import { initTheme } from './composables/useTheme';
import router from './router';
import { vPermission } from './shared/directives/permission';
import './shared/styles/fonts.css'; // 普惠体注册（本地字面优先，须在 tokens 前）
import './shared/styles/tokens.css';
import './shared/styles/adaptive.css';

const app = createApp(App);

initTheme(); // 首帧前落 .dark 类（localStorage 记忆；默认浅色，对齐 DESIGN.md §Colors）

app.directive('permission', vPermission);

app.use(createPinia());
app.use(router);
app.use(ElementPlus);
app.mount('#app');
