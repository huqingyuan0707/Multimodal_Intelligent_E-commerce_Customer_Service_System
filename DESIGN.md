---
name: 多模态智能电商客服系统
description: 深色科技风客服工作台——买家看结果，坐席看过程，运营看效果
colors:
  primary: "#4f6bff"
  accent: "#22d3ee"
  gold: "#e8a33d"
  online: "#34d399"
  notice: "#fb9236"
  bg: "#0b1124"
  card: "#161d33"
  card-2: "#1e2742"
  text-main: "#eef1f8"
  text-muted: "#8b94ad"
  bubble-user: "#4f6bff"
  bubble-agent: "#f2f5fc"
  text-on-light: "#1f2430"
  purple: "#8b5cf6"
typography:
  display:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "64px"
    fontWeight: 800
    lineHeight: 1
  title:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "8px"
  md: "12px"
  pill: "999px"
spacing:
  sm: "8px"
  md: "12px"
  lg: "16px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.pill}"
    padding: "6px 16px"
  card-glass:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.md}"
    padding: "16px"
---

# Design System: 多模态智能电商客服系统

> 来源：`frontend/src/shared/styles/tokens.css`（唯一色值事实源）+ `页面设计.md §2` 深色科技风 + `design.pen` 18/18 画板。tokens 为准，文字只讲用法。

## Overview

**Creative North Star: "深空调度台"**

深空蓝底加蓝紫弥散渐变，玻璃拟态卡片承载三类视图：买家端只给结果（对话泡加引用角标），坐席端展开过程（Trace 加工具卡加检测卡），运营端看效果（指标加归因表）。品牌表达收敛在顶栏渐变、主按钮蓝和引用金三处，其余一律克制。拒绝渐变文字、Inter 字体、紫粉套路。

**Key Characteristics:**

- 深色优先，所有文字 token 化，`.vue` 内零硬编码色值
- 气泡语义固定：用户品牌蓝右置，智能体白底左置
- 语义卡三色：VLM 蓝框、引用金框、预警橙底

## Colors

深空底加三强调色，语义不混用。

### Primary

- **调度蓝** (#4f6bff)：主按钮、用户气泡、选中态、发送键。任何一屏占比最低但最先被看到。
- **信号青** (#22d3ee)：波形、描边、次级强调、播放态。
- **在线绿** (#34d399)：在线态、成功态、召回通过原因。

### Secondary

- **引用金** (#e8a33d)：RAG 引用角标与溯源卡描边，专属引用语义。
- **预警橙** (#fb9236)：待发货、金额、徽标、预警。画板与代码统一用此橙，不另起 `#ff5a36/#ff8400`。

### Neutral

- **深空底** (#0b1124)：页面底。
- **卡片** (#161d33)：一级卡。**卡片次级** (#1e2742)：悬浮、输入底、波形底。
- **正文** (#eef1f8)：主文字。**次要文字** (#8b94ad)：摘要、时间、口径注释。
- **智能体泡** (#f2f5fc，配字 #1f2430)：左置白泡。**玻璃浮层** (rgb(22 29 51 / 60%) + 边框 rgb(255 255 255 / 12%))：弹窗与错误页卡片。

### Named Rules

**The Token-Only Rule.** 色值只许出现在 `tokens.css`，`.vue`/canvas 一律 `var(--reai-*)`（canvas 运行时读 token，见 `VoicePanel.vue`）。

**The One-Orange Rule.** 橙只用 `--reai-notice` (#fb9236) 及其 12% 柔底，禁止再发明相近橙红。

## Typography

**Display Font:** system-ui（含 PingFang SC / Microsoft YaHei 回退）
**Body Font:** system-ui（含 PingFang SC / Microsoft YaHei 回退）
**Label/Mono Font:** monospace（仅 trace_id、单号、波形元数据）

**Character:** 无定制字体，靠字号字重拉开层级；中文文案真实业务口径，不写示例文本。

### Hierarchy

- **Display** (800, 64px, 1)：403/500 错误码数字，实色 `--reai-text-main`，禁用渐变裁字。
- **Title** (600, 18px, 1.4)：页头、卡片标题。
- **Body** (400, 13px, 1.5)：消息泡、表单、表格主体，最大行宽不限但气泡限 70-85%。
- **Label** (400, 12px, 1.5)：摘要、时间、口径、空态引导。
- **Mono** (400, 12px, 1.5)：trace_id、运单、上下文用量。

### Named Rules

**The Solid-Code Rule.** 错误码大数字用实色，不用 `background-clip: text` 渐变字。

## Layout

三栏工作台（280px 队列｜自适应会话｜300px 客户信息），买家页双栏（280px 历史｜960px 上限对话），大屏指标行加下钻区。`≥1280` 三栏，`768-1280` 右栏折叠为抽屉，`<768` 单列加底部 Tab。间距 4 的倍数（8/12/16），卡片圆角 12，胶囊 999。

## Elevation & Depth

 tonal 分层为主，阴影为辅。卡片用 `--reai-glow`（0 0 24px rgb(79 107 255 / 25%)）微发光加 `backdrop-filter: blur(12px)` 玻璃拟态；投影只用 `--reai-shadow-card` (0 2px 12px rgb(0 0 0 / 40%))。

### Named Rules

**The Glow-Not-Shadow Rule.** 深度靠底色差（bg/card/card-2）表达，发光只用于玻璃卡当前态，不做大面积投影。

## Shapes

圆角语言：卡片 12、输入 22（胶囊行）、徽标快捷 999、气泡用户右上 2 其余 12、智能体左上 2 其余 12。边框 `rgb(255 255 255 / 8%)`，语义卡描边用对应语义色 1px。

## Components

### Buttons

- **Shape:** 胶囊 (999px)，危险/链接用 Element 链接态
- **Primary:** 调度蓝底加主文字，内边距 6px 16px
- **Hover / Focus:** Element 默认加可见焦点环；破坏操作先 `ElMessageBox.confirm`
- **Voice/Image:** 图片与语音入口必须带 `aria-label`（上传图片/语音输入），播放键带 `播放语音 <id>`

### Cards / Containers

- **Corner Style:** 圆角 12
- **Background:** 玻璃浮层或一级卡
- **Shadow Strategy:** 见 Elevation，微发光
- **Border:** 玻璃边框或 8% 白边
- **Internal Padding:** 14-16px，消息流 20px

### Inputs / Fields

- **Style:** 卡片次级底，圆角 8-22，中文占位
- **Focus:** 可见焦点环，键盘可达
- **Error / Disabled:** `ElMessage` 成功失败必报；`meta.roles` 无权按钮禁用或不出现

### Navigation

顶栏品牌加 Tab（路由 `meta.title` 生成，按 `meta.roles` 过滤），`/login` 与异常页独立无壳。面包屑标签页统一布局，`keep-alive` 只用于 workbench/chat。

### Citation Card

金框引用溯源卡：角标 `[n]` 可点跳原文，附 `trace_id` 一键复制，坐席与买家同源。

### Vision Card

蓝框 VLM 检测卡：类别加置信度加描述，`<0.6` 显示已转人工复核，不硬答。

## Do's and Don'ts

### Do:

- **Do** 所有列表页配 `el-pagination`（默认 20，可切 10/20/50/100）。
- **Do** 空/加载/错误三态齐全（`el-empty` 中文引导、`v-loading`、错误重试加转人工）。
- **Do** 语音图片按钮写 `aria-label`，图片写 `alt`。
- **Do** 破坏操作（删除/停用/归档/驳回）先二次确认。

### Don't:

- **Don't** 用渐变文字做标题数字（AI 套路，已在 403/500 清除）。
- **Don't** 在 `.vue`/TS 里散写色值（`#fff/#ff5a36/#7c6cf0` 类已收敛）。
- **Don't** 用 `Inter` 字体或紫粉 135deg 渐变。
- **Don't** 页面直写 `fetch`（走 `src/api` 唯一入口），401 走中央 `handle401()`。
