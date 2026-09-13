// 应用入口（只做装配：router+pinia+样式，对齐页面设计 §2）
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import 'element-plus/theme-chalk/dark/css-vars.css';
import { createPinia } from 'pinia';
import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import { vPermission } from './shared/directives/permission';
import './shared/styles/tokens.css';
import './shared/styles/adaptive.css';

const app = createApp(App);

document.documentElement.classList.add('dark'); // Element Plus 暗黑（对齐页面设计 §2）

app.directive('permission', vPermission);

app.use(createPinia());
app.use(router);
app.use(ElementPlus);
app.mount('#app');
