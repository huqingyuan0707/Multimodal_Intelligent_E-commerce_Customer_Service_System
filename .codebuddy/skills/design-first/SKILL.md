---
name: design-first
description: 设计先行工作流（.pen 出图 → 按图写代码）。改 frontend/src 下任何 UI 代码、或在 design.pen 新建/修改画板前加载，含输入清单、.pen 字段速查、深色 token 映射表、状态完整性清单与 MCP 降级操作。
---

# 设计先行（`design.pen` → 代码 · 本项目强制流程）

> 红线见 `.codebuddy/rules/design-first.mdc`；机检见 `scripts/check_design.py`（CI `design-guard`）。
> 本 Skill 只写机器查不出来的部分。

## 1. 适用场景
新增/调整任何页面、组件、布局、配色 → 先动 `design.pen`。只改逻辑（`api/stores/composables/types`）→ 不必加载。

## 2. 输入清单（缺一个就先补，不猜）
| 要什么 | 去哪拿 |
|---|---|
| 这一页解决什么 | `多模态智能电商客服系统需求文档-FRDv2.md` 对应角色/场景章节 |
| 路由 / 页面详设 / 组件清单 | `页面设计.md` §1 路由表、§3 页面详设、§7 组件清单 |
| 视觉语言与布局壳 | `页面设计.md` §2（深色科技风 + 玻璃拟态） |
| 可用色 / 圆角 / 阴影 | `frontend/src/shared/styles/tokens.css`（唯一事实源） |
| 可复用组件 | `frontend/src/{components,entities,shared/components}` |
| 真实数据形状 | `src/types/*.ts`、`API接口与SSE事件协议规范.md` |

## 3. 画板规范
- **一页一 frame**，命名 `<中文标题>-/<route>`；顶层画板 x 轴平铺，步进 1340（现有 0 / 1340 / 2680 / 4020），`1280×800`，`y=0`。
- 层级深度 ≤ 5，超过说明该拆组件。
- 画板内组件名对齐 `页面设计.md` §7 组件清单（`ChatPanel/TracePanel/CustomerPanel/QuickReply/...`）→ 代码照这个名字建文件，避免「画板叫 A、代码叫 B」。
- 文案用真实中文业务文案（「袖口脱线约2cm · 置信度 0.82」），禁止「示例文本」——文案是设计的一部分。

## 4. `.pen` 格式速查
纯 JSON 文本（`{"version": "2.17", "children": [...]}`），可直接读写；`pencil.execute` 只是另一种改法。

| 字段 | 说明 |
|---|---|
| `type` | `frame` / `text` / `rectangle` / `ellipse` / `icon` |
| `id` | 画板内唯一稳定标识，改结构时保持不变（diff 可读） |
| `name` | 中文可读名；顶层 frame 必须是 `<中文标题>-/<route>` |
| `layout` | `horizontal` / `vertical` + `gap` / `padding` / `justifyContent` / `alignItems` |
| `width`/`height` | 数字 或 `"fill_container"` |
| `padding` | 数字 或 `[上下, 左右]` 或 `[上, 右, 下, 左]` |
| `fill`/`stroke`/`cornerRadius` | 色值/边框/圆角；`"strokeWidth": {"bottom": 1}` 只画某边 |
| `text` | `content` + `fontSize` + `fontWeight` + `lineHeight` + `fill`；长文本加 `"textGrowth": "fixed-width"` + `width` |
| `icon` | `library: "lucide"` + `icon: "<name>"` |

## 5. 深色 token 映射（画板色值一律从此表取）
| 用途 | 画板值 | 代码 |
|---|---|---|
| 页面底 | `#0b1124` | `var(--reai-bg)` |
| 卡片 | `#161d33` | `var(--reai-card)` |
| 卡片次级/悬浮 | `#1e2742` | `var(--reai-card-2)` |
| 主色/主按钮 | `#4f6bff` | `var(--reai-primary)` |
| 强调/描边 | `#22d3ee` | `var(--reai-accent)` |
| 成功/在线 | `#34d399` | `var(--reai-online)` |
| 警告 | `#fb9236` | `var(--reai-notice)` |
| 金/引用角标 | `#e8a33d` | `var(--reai-gold)` |
| 正文 | `#eef1f8` | `var(--reai-text-main)` |
| 次要文字 | `#8b94ad` | `var(--reai-text-muted)` |
| 边框 | `rgb(255 255 255 / 8%)` | `var(--reai-border)` |
| 用户气泡 | `#4f6bff` | `var(--reai-bubble-user)` |
| AI/客服气泡 | `#f2f5fc`（文字 `#1f2430`） | `var(--reai-bubble-agent)`（`--reai-text-on-light`） |
| 玻璃态浮层 | `rgb(22 29 51 / 60%)` + `rgb(255 255 255 / 12%)` | `var(--reai-glass-bg)` / `var(--reai-glass-border)` |
| 语义卡底（VLM / 引用溯源 / 预警） | `#4f6bff1f` / `#e8a33d1f` / `#fb92361f` | `var(--reai-primary-soft)` / `--reai-gold-soft` / `--reai-notice-soft` |
| 卡片阴影 / 页背景 | — | `var(--reai-shadow-card)` / `var(--reai-page-gradient)` |

**新增色值顺序**：`tokens.css` 加变量 → 画板用它的值 → 代码用 `var()`。不能反。

## 6. 画板必须体现的状态（否则代码里一定缺）
- **三态**：加载中（骨架/`v-loading`）、空态（`el-empty` + 中文引导）、错误态（可重试 + 降级到 `@/mock`）。
- **列表**：分页控件（`el-pagination`，默认 20，可切 10/20/50/100）——对齐前端红线 §7，禁止全量列表画板。
- **权限**：`meta.roles` 无权的按钮画成禁用/不出现，并在画板上注明角色。
- **破坏性操作**：删除/停用/归档/审批驳回 → 画出 `ElMessageBox.confirm` 的二次确认形态。
- **长内容**：溢出策略要画出来（截断+tooltip / 滚动区 / 折叠）。
- **多模态与溯源**（本项目特色）：图片/VLM 检测卡、语音转写、引用溯源角标 `[n]`、审批留痕，都要在对应画板出现。

## 7. 从画板落到代码
- 色值 → `var(--reai-*)`；间距/圆角 → 照抄画板数值（4 的倍数）。
- 层级/结构 → 模板 `<section>` 分块与画板 frame 一一对应，顺序一致。
- 组件 → 优先复用 `AiButton/AiInput`；画板里的「卡片/气泡/角标」若在多页重复出现，先抽 `components/` 再写页面。
- 页面方法一律箭头函数（`func-style` 硬拦）；样式 `scoped`。
- 完成前：`pnpm lint && pnpm typecheck && pnpm build`，并 `python scripts/check_design.py --staged`。

## 8. MCP 用法与降级
- **首选**：`pencil.execute` 在当前打开的画布上改（工具参数经 `mcp_get_tool_description` 确认后再调）。
- **降级**：报 `transport not connected to app: codebuddy` / 工具不存在 → 直接读写 `design.pen` 文本 JSON（§4 字段表），**效果等同，不得跳过设计**。
- 任何情况下都不允许以「MCP 不可用」为由跳过画板直接写 UI 代码。
