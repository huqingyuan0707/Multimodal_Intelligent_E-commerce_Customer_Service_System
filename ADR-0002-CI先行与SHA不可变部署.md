# ADR-0002：CI 先行、短 SHA 不可变部署、部署仓库分离的决策

- 日期：2026-09-13
- 状态：已落地（CI 扫描告警级；部署仓库联动待配 vars.DEPLOY_REPO 后生效）
- 决策人：项目负责人（六条落地建议确认）
- 关联文档：部署工程化.md §五/§十二/§十三、`.github/workflows/`、 `deploy/argocd/`

## 1. 背景与约束
- 现状与问题：`ci.yml` 只有 lint/test/build 门禁，无安全扫描；镜像虽已推短 SHA tag，但 compose/deploy 默认走 `latest`，部署不可追溯到 commit；应用仓与部署态混在一起，ArgoCD 无法做权限隔离；生产无人工审批卡点。
- 约束：每次提交必须有质量门禁（任一红灯不合并）；每次部署必须可追溯到具体 commit；回滚 <5min；生产发布必须人工审批；初期不给团队加过大门禁负担。

## 2. 候选方案
| 方案 | 优点 | 缺点 | 成本 |
|---|---|---|---|
| A（本决策）：CI 先行 + 短 SHA + 扫描先告警 + 部署仓分离 + prod 手动同步 | 门禁渐进、部署可追溯、权限隔离、回滚即切 tag | 需新建部署仓库并配 PAT/vars | 低（纯 YAML + 文档） |
| B（现状）：latest 直部 + 扫描后补 | 零改动 | 不可追溯、无审批、无隔离 | 风险高 |
| C：一步到位全硬门禁 + prod 自动同步 | 自动化彻底 | 初期误拦多、生产无人工卡点 | 高 |

## 3. 决策
- 选择：A，分两步走——先做 CI（lint → test → build 门禁已通，本次补扫描告警），再做 CD（部署仓联动 + ArgoCD，`kubectl apply` 手动部署保留为过渡）。
- 理由（对照约束逐条）：
  1. CI 门禁：沿用 `ci.yml` 现有顺序，后端 ruff → mypy → pytest、前端 lint → typecheck → test → build，任一步骤失败即停。
  2. 可追溯：`package.yml` 已推 `latest + 短 sha + 版本号`；`cd-update.yml` 把触发 commit 的短 sha 写进部署仓 `envs/dev/kustomization.yaml`（前后端同 tag），部署与 commit 一一对应；compose 本地默认 `latest` 仅用于开发联调。
  3. 扫描渐进：`security` job（Trivy fs）与镜像扫描统一 `exit-code: 0` 只告警；团队适应后改 `1` 即转硬门禁（一行变更）。
  4. 权限隔离：应用仓开发者提交，部署仓仅 CI bot 写入（PAT），ArgoCD 只监听部署仓。
  5. 生产审批：`reai-prod` Application 不设 `automated`，发布 = 人工改 prod tag + 点 Sync。

## 4. 后果
- 正面：提交即有门禁；部署可追溯；回滚 = 切 tag（<5min）；生产有人审。
- 负面/风险 + 缓解：部署仓/PAT 未配时 `cd-update` 仅告警跳过（不阻断 package）——缓解：CI 日志有 notice，配好即生效；prod 手动同步依赖人执行——缓解：§十三写死回滚步骤。
- 回滚方案：ArgoCD 路径把部署仓 tag 改回上一版本并 Sync；compose 路径 `deploy.ps1 -Tag <上一版本>`；DB 迁移保持向前兼容（先加字段后发代码再删旧字段）。
- 可观测验证：`deploy.ps1` 健康检查（后端容器/前端首页/Nginx 反代/登录 token）4 PASS；ArgoCD 应用 Healthy + Synced 即发布成功。

## 5. 落地清单
- [x] `ci.yml` security job（Trivy fs，告警级）+ 尾注更新
- [x] `package.yml` 前后端镜像 Trivy 扫描（告警级）
- [x] `cd-update.yml`（package 成功 → 部署仓 dev tag = 短 sha）
- [x] `deploy/argocd/reai-dev.yaml`（自动同步）/ `reai-prod.yaml`（手动同步）
- [x] 部署工程化.md §五/§十二/§十三同步
- [ ] 建部署仓库 + 配 `vars.DEPLOY_REPO` / `secrets.DEPLOY_PAT`（人工一次）
- [ ] 扫描 exit-code 0 → 1 转硬门禁（团队适应后）
- [ ] ArgoCD 接入部署仓 + prod 发布审批演练 + 回滚演练（RTO 验证）
