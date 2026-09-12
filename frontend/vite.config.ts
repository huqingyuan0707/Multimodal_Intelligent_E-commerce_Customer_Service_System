// Vite 基础配置（@=src，对齐前端工程化构建节）+ Vitest 单测配置
// coverage.clean=false：Windows 下启动前删除 coverage/ 会被 IDE 安全删除策略拦截而直接失败，
// 保留上次报告不影响本轮结果判定（CI 为 Linux 环境，不受影响）。
import { fileURLToPath, URL } from 'node:url';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.{test,spec}.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      clean: false,
    },
  },
});
