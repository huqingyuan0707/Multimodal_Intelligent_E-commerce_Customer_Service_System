---
name: frontend-code-style
description: breath After modifying any code under frontend/src, follow this skill so new code matches the project's Vue3 + TypeScript + Element Plus conventions (API layer, stores, SSE, styles, commits).
---

# 前端代码风格（Vue3 + TS + Element Plus · 本项目强制约定）

## 1. 基础（必须遵守）
- 包管理只用 **pnpm**；`<script setup lang="ts">` + Composition API；`@` = `src/`。
- Prettier（`.prettierrc`）：`semi: true, singleQuote: true, tabWidth: 2, printWidth: 100, arrowParens: avoid, endOfLine: lf`。**ESLint 必须 0 errors**（`@typescript-eslint/no-explicit-any` 为 warn，既有 `any` 不扩散、新代码优先写类型）。
- **页面方法一律箭头函数**：禁止 `function foo() {}` / `async function foo() {}` / `export function foo()` 声明，一律写成 `const` 箭头函数（ESLint `func-style: expression` 已硬约束，提交即拦截）：
```ts
// ✅ 页面方法
const loadDocs = async () => { /* ... */ };
const govPayload = () => ({ security_level: govForm.security_level });
export const request = async <T = any>(path: string, options: RequestInit = {}): Promise<T> => { /* ... */ };
// ❌ 禁止
async function loadDocs() { /* ... */ }
```
  注意：箭头函数无提升，定义必须出现在调用之前（顶层立即调用尤其注意）；无 `this`/`arguments` 依赖时才可转（本项目页面层已确认无此依赖）。

## 2. 目录（新代码必须落到新架构）
```
src/features/<domain>/{api,components,composables,stores,types,views}
src/{entities,shared/{components,composables,utils,types,styles}}
```
- 存量 `src/views/*` 只修不扩；新业务建 `features/<domain>`。
- Agent 相关类型先行：`features/agent/types/agent.ts`（`Message/Reference/AgentEvent/...`），禁止各文件自造消息形状。

## 3. API 层唯一入口（`src/api/index.ts`，禁止页面直写 fetch）
```ts
// JSON：走 request<T>，自动解包 {code,msg,data,trace_id}，code!==0 抛带 code 的 Error
export const data = await api.listDocuments();
// 上传：FormData，绝不手设 Content-Type（浏览器自动生成 multipart 头）
const fd = new FormData();
fd.append('file', file);
return request('/documents/upload', { method: 'POST', body: fd });
// SSE：fetch + 必须带 Authorization（教训：缺头会导致 401 → 本地模拟 → 服务端无记录）
fetch(`${BASE}/chat`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem('reai_token') ?? ''}` },
  body: JSON.stringify(p),
});
// GET query 参数一律 encodeURIComponent
```
- 401（HTTP 或业务码 `1002`）走中央 `handle401()` 清登录态跳登录页，**禁止各页面自写跳转**。

## 4. 状态与组合式函数
- Pinia 只用 setup 风格：`defineStore('session', () => { refs + computed + functions })`（参考 `features/agent/stores/session.ts`），按业务域拆 store。
- 可复用逻辑抽 `composables/useXxx.ts`（如 `useAgentStream` 管 SSE 重连，`useChat` 管发送/阶段/技能/反馈），页面只做编排。
- SSE 解析固定范式：`event: / data:` 正则分帧 → `phase/message/done` 分支；`done` 的 `JSON.parse` 必须 try/catch。

## 5. 组件与 UI
- 优先用 `AiButton / AiInput`（`@/components`）而非裸 `el-button/el-input`；Element Plus 靠 `unplugin-auto-import + unplugin-vue-components` 按需引入，**禁止全局全量引入**。
- 样式用设计 tokens：`var(--reai-primary / --reai-card / --reai-text-main / --reai-text-muted / --reai-border / --reai-shadow-*)`，`<style scoped>`；禁止硬编码主色。
- 反馈规范：成功/失败一律 `ElMessage`；删除/停用/归档等破坏性操作先 `ElMessageBox.confirm`。
- 枚举中文化用映射表（如 `LEVEL_TAG = { public: '公开', internal: '内部', confidential: '机密' }`），禁止模板里散落字面量。

## 6. 数据与降级
- 列表页 `onMounted` 调真实接口，`catch` 回退 `@/mock` 演示数据（参考 `KnowledgeView::loadDocs`），保证后端不可用时页面可用。
- 新会话本地先建 `t-${Date.now()}`，发送成功后以后端记忆为准；切会话优先 `api.getSession(id)` 恢复，404 再回退 mock。

## 7. 文案与注释
- 界面文案与注释用中文；复杂 Var（如治理/运营指标）旁边写一行注释说明口径。

## 8. 提交与验证（必跑）
- commit 走 commitlint：`feat/fix/docs/style/refactor/perf/test/chore/revert/build/ci` + sentence-case 主题 ≤100 字符。
- 改完必跑：`pnpm lint`（0 errors）、`pnpm typecheck`、`pnpm build`；改 store/composable 加 `vitest` 用例（`src/**/*.test.ts`）。
