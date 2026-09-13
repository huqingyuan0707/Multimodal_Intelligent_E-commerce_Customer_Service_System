---
name: frontend-code-style
description: breath After modifying any code under frontend/src, follow this skill so new code matches the project's Vue3 + TypeScript + Element Plus conventions (API layer, stores, SSE, styles, commits).
---

# 前端代码风格（Vue3 + TS + Element Plus · 本项目强制约定）

## 1. 基础（必须遵守）
- 包管理只用 **pnpm**；`<script setup lang="ts">` + Composition API；`@` = `src/`。
- Prettier（`.prettierrc`）：`semi: true, singleQuote: true, tabWidth: 2, printWidth: 100, arrowParens: avoid, endOfLine: lf`。**ESLint 必须 0 errors**（类型规则已放宽：`no-explicit-any / explicit-function-return-type / explicit-module-boundary-types` 均为 off，`no-unused-vars` 为 warn）。
- **类型宽松、推断优先 + 三词禁令**：返回值类型注解一律不写（`: AgentMessage`、`<PromoItem>` 等靠推断）；**`void`、`Promise<`、`Record<` 三个词禁止在 `src/` 出现**——映射表用 `as const` + `keyof typeof`，`Record<string, unknown>` 字段写 `object`，回调类型返回值写 `=> unknown`，`defineEmits` 用运行时数组形式，fire-and-forget 直接 `fn()`（禁 `void fn()` 前缀，ESLint `no-restricted-syntax` 已硬拦）；保留 `ref<T>` 泛型与参数对象类型；`any` 可用。
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
src/views/<domain>/{AdminView,ChatView,LoginView,...}  # 页面按域分目录
src/{components,composables,stores,types}              # 逻辑按层放顶层（无 features/）
src/{entities,shared/{components,composables,utils,types,styles}}
```
- 页面建 `src/views/<domain>/` 下对应目录；逻辑按层放顶层 `components/composables/stores/types`，通用件下沉 `shared`。
- Agent 相关类型先行：`src/types/agent.ts`（`Message/Reference/AgentEvent/...`），禁止各文件自造消息形状。

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
- Pinia 只用 setup 风格：`defineStore('session', () => { refs + computed + functions })`（参考 `src/stores/session.ts`），按职责拆 store。
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
