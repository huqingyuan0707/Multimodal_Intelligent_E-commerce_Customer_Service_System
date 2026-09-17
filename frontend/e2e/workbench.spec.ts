// 工作台 E2E 冒烟：守卫弹回 → 登录回跳 → 队列渲染（接口全部 page.route mock，不依赖 8000 服务）
// 口径：信封 {code:0,msg,data}；token 走 sessionStorage.reai_token（stores/user.ts）；
// 登录返回 {token, user}（types/user.ts），队列行是后端 snake_case（api/workbench.ts WorkbenchRow）。
import { expect, test } from '@playwright/test';

const envelope = (data: unknown) => ({ code: 0, msg: 'ok', data, trace_id: 'e2e' });

// 身份：roles 含 admin 才能过路由守卫的 meta.roles（/workbench 要求 cs/admin）
const me = { name: 'admin', tenant: 'demo-tenant', roles: ['admin'], perms: ['admin'] };

// 队列页：composable 读 res.items 再 toRow 映射（username→姓名、handoff_status→标签）
const queuePage = {
  items: [
    {
      id: 'h1',
      title: '退货咨询',
      username: '王小明',
      created_at: '2026-09-16T00:10:00',
      updated_at: '2026-09-16T00:12:31',
      message_count: 3,
      handoff_status: 'pending',
      handoff_label: '待接',
      assignee: '',
      handoff_reason: '情绪激动',
      resolution: '',
      last_message: '我要退那个充电宝',
    },
  ],
  total: 1,
  page: 1,
  size: 20,
};

test.beforeEach(async ({ page }) => {
  // 兜底空信封先注册：其余接口返回空数据，页面走空态 + 中文提示，不允许白屏/崩溃。
  // login/me/queue 三个关键路径 route.fallback() 落到后面的精确 mock（兼容两种注册序匹配）。
  await page.route('**/api/v1/**', async route => {
    const url = route.request().url();
    if (
      url.includes('/auth/login') ||
      url.includes('/auth/me') ||
      url.includes('/workbench/queue')
    ) {
      await route.fallback();
      return;
    }
    await route.fulfill({ json: envelope([]) });
  });
  await page.route('**/api/v1/auth/login', route =>
    route.fulfill({ json: envelope({ token: 'e2e-token', user: me }) }),
  );
  await page.route('**/api/v1/auth/me', route => route.fulfill({ json: envelope(me) }));
  await page.route('**/api/v1/workbench/queue**', route =>
    route.fulfill({ json: envelope(queuePage) }),
  );
});

test('未登录访问工作台被守卫弹回登录页', async ({ page }) => {
  await page.goto('/workbench');
  await expect(page).toHaveURL(/\/login/);
});

test('登录成功回跳工作台并渲染队列', async ({ page }) => {
  // 直访工作台 → 守卫弹回 /login?redirect=/workbench → 登录后回跳（LoginView 只认 redirect query）
  await page.goto('/workbench');
  await page.getByPlaceholder(/账号/).fill('admin');
  await page.getByPlaceholder(/密码/).fill('admin123');
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await expect(page).toHaveURL(/\/workbench/);
  // 「王小明」在队列行与中栏头部各出现一次，strict 模式需收敛到 first
  await expect(page.getByText('王小明').first()).toBeVisible({ timeout: 8000 });
  await expect(page.getByText('我要退那个充电宝')).toBeVisible();
});
