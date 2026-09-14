# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- 买家：在售前/售中/售后 3 步内闭环（查库存、物流、退换），经 `/chat` 与 `/widget` 进入。
- 客服/坐席：在 `/workbench` 10 秒内看懂 Agent 过程并一键接管，处理转人工、审批、售后单。
- 运营/店长/仓管/财务/管理员：在知识库、商品、库存、订单、营销、物流、风控、对账、大屏完成经营闭环。

## Product Purpose

多模态智能电商客服系统：同一 Agent 内核，买家看结果、坐席看过程、运营看效果。文本/图片/语音三模态经统一 SSE 事件加引用溯源加审批留痕交付。成功即自动解决率达标且全链路可追溯（`trace_id`）。

## Positioning

图文售后招牌链：上传瑕疵图经 VLM 检测拼进 LLM 上下文，低置信（<0.6）转人工；RAG 双路召回加治理过滤加无据拒答（2001），引用必现可跳。

## Operating Context

- 路由 18 条（`页面设计.md §1`）：`/login/chat/workbench/tasks/approvals/knowledge/studio/dashboard/admin/goods/inventory/purchase/orders/finance/screen/marketing/logistics/risk`，另有代码先行 `/aftersales/reviews/widget` 与异常 `/403/404/500`。
- 角色经 `meta.roles` 加 `v-permission` 加接口 `require_perm` 三重，401 走中央 `handle401()`。
- SSE 事件 `source/phase/message/done`，`done` 含 `references/guard/faithfulness/trace_id`。

## Capabilities and Constraints

- 已落地：JWT、文本 SSE 主线、RAG 真检索（BM25/rerank 为 P1 缺口）、退款审批闭环、图片链路 MVP、compose/GHCR/ArgoCD 部署、`design.pen` 18/18。
- 约束：可调全进 `Settings`；向量/关键词走适配层；阻塞 IO 走 `to_thread`；模型挂了降级绝不 500；列表分页默认 20 可切 10/20/50/100；色值只许在 `tokens.css`。
- 未决（推断，待确认）：真机视觉集复测口径、ASR/TTS 网关选型、生产 PG/Redis/S3 切换窗口。

## Brand Commitments

深色科技风加玻璃拟态（`页面设计.md §2`）；顶栏蓝紫渐变、调度蓝主按钮、引用金溯源卡为绑定视觉；`design.pen` 为 UI 唯一事实源。

## Evidence on Hand

- `多模态智能电商客服系统需求文档-FRDv2.md`、API/SSE 协议、数据模型、RAG 治理、测试验收方案、`执行步骤.md v0.1.6`。
- 企业知识库种子 29 篇（`docs/knowledge-base/`）；`design.pen` 18 画板；`DESIGN.md` 由本次 document 扫描生成。

## Product Principles

- 主线先竖通再横铺：按 A 多模态→B Runtime→C 转人工→D 生产存储→E 评估推进。
- 同一行为只允许一个实现；能进门禁的不写进文档。
- 无据不答：宁可 2001 拒答转人工，不幻觉。
- 渐进披露：买家极简，坐席全 Trace，运营全归因。

## Accessibility & Inclusion

- 对比度 AA，键盘可达，抽屉焦点 trap，语音/图片按钮 `aria-label`，图片 `alt`；投屏脱敏 PII。
