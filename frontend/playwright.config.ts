// Playwright E2E 配置（对齐前端工程化 §测试：组件层归 vitest，跨页链路归此处）
// 运行：pnpm test:e2e（首次需 pnpm exec playwright install chromium）
// CI 暂不启用：需要浏览器下载 + 前端 dev server，待工作台链路稳定后接入（见执行步骤.md）。
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
