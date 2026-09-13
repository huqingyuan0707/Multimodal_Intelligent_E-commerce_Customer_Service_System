# 长期记忆（跨会话）

## 项目：多模态智能电商客服系统（Agent + RAG 电商客服）

- 工作区当前以**文档先行**为组织方式：`多模态智能电商客服系统需求文档-FRDv2.md`、`电商开发文档.md`、`前端工程化.md`、`后端工程化.md`、`部署工程化.md`、`数据模型与存储设计.md`、`API接口与SSE事件协议规范.md`、`RAG知识库构建检索治理规范.md`、`测试评估验收方案.md`。
- 目标代码结构：`backend/`（FastAPI）+ `frontend/`（Vue3 + TS + Element Plus + Pinia，页面 `frontend/src/views/<domain>/` + 逻辑顶层 `components/composables/stores/types/`，无 `features/`）。

## 工程约定：软约束 + 硬约束双层

- **Skill / Rules 是软约束**，靠语义触发、可能被忽略或被更高优先级的用户指令覆盖，**不能保证 AI 严格遵守**。
- 可靠性排序：`CI 拦截 > pre-commit hook > ESLint/TS 报错 > always-apply 规则 > Skill > 文档`。
- 因此新增「必须遵守」的约定时，**优先写成可执行的检查**，而不是只写进文档；Skill 只保留机器查不出来的内容（分层职责、响应信封、错误码分段、租户隔离口径、SSE 事件名）。
- 禁止用 `eslint-disable` / `noqa` / `type: ignore` 让门禁变绿。

## 文档清单（root，共 13 份 md）与口径基准

| 文件 | 定位 |
|---|---|
| `AGENTS.md` | **人与 AI 的唯一执行入口**：文档索引 + AI 工作流 + 前后端红线 + 命令速查（只索引，不复制正文） |
| `README.md` | 人面向入口（本项目已生成，16 节） |
| `多模态智能电商客服系统需求文档-FRDv2.md` | 自述 FRD v2.0 |
| `电商开发文档.md` | 自述 FRD v3.0（声称替代原架构指南版） |
| `前端工程化.md` / `后端工程化.md` / `部署工程化.md` | 分层与工程化细则 |
| `页面设计.md` | IA 路由表 §1 / 页面详设 §3 / 组件清单 §7 / DoD §8 |
| `API接口与SSE事件协议规范.md` | 信封、错误码、SSE、端点清单 |
| `数据模型与存储设计.md` | PG DDL / 向量适配层 / Redis 键 / S3 布局 |
| `RAG知识库构建检索治理规范.md` | 入库 + 双路召回→RRF→重排→治理→拒答 2001 |
| `测试评估验收方案.md` | 测试金字塔 / smoke 规范 / 黄金集 ≥500 / CI |
| `ADR规范与模板.md` | 选型变更先写 ADR，不改代码 |

⚠️ **已知口径冲突**：两份 FRD 版本交叠（`AGENTS.md` 指向 FRDv2，`电商开发文档.md` 自称 v3）；SSE 事件形态在 v3 里仍是旧的 `text/tool_call/tool_result` 写法。**以 `API接口与SSE事件协议规范.md` §5 的 `source/phase/message/done` 为项目实际形态。**

## 关键路径

| 用途 | 路径 |
|---|---|
| 编辑器技能（项目级，会被自动扫描） | `.codebuddy/skills/<name>/SKILL.md` |
| 编辑器技能（用户级，跨项目） | `C:\Users\qingy\.claude\skills\<name>/SKILL.md` |
| 常驻规则（alwaysApply，不依赖触发） | `.codebuddy/rules/*.mdc` |
| 规则 frontmatter 字段 | `description` / `alwaysApply` / `enabled` |

## 本地启动约定（已跑通）

| 项 | 值 |
|---|---|
| 后端端口 | **8000**（`frontend/vite.config.ts` 的 `server.proxy` 把 `/api` 指向 `http://127.0.0.1:8000`；AGENTS.md 命令速查里写的 8010 是错的） |
| 前端端口 | 5173 |
| 后端 venv | `backend/.venv`，启动命令 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| 前端启动 | `cd frontend; pnpm dev` |
| 依赖 | `.env` 可不建（`Settings` 默认值够用）；后端依赖清单见 `backend/requirements.txt` |
| 开发默认账号 | 租户 `demo-tenant` / 用户名 **admin** / 密码 **admin123** / 角色含 B 端权限（全走 `Settings.SEED_*`，`.env` 可覆盖；改密码/改角色只对**新建**账号生效，种子不覆盖已存在账号——老 dev.db 需手动补 roles 或删库重起） |
| 鉴权配置 | `Settings`: `ACCESS_TOKEN_EXPIRE_SECONDS` / `JWT_ALGORITHM` / `PASSWORD_HASH_ITERATIONS` / `PASSWORD_SALT_BYTES` / `ROLES_SEPARATOR` / `SEED_*`；角色解析唯一口径 `core/security.py::split_roles()`；`ENV=prod` 有 fail-fast 护栏（默认或 <32 字符的 `JWT_SECRET`、`SEED_ON_START=true` 都会**导入配置即报错**）；改哈希迭代次数须重刷存量密码 |
| 大模型（ADR-0001） | 生成走**本地 Ollama `qwen2.5:0.5b`**，OpenAI 兼容端点 `http://127.0.0.1:11434/v1`；唯一出口 `app/services/llm_service.py`（`complete()/probe()`，`_post/_get` 打桩，**`trust_env=False` 防系统代理劫持 localhost**）。`LLM_*` 九项进 Settings；任何失败收敛为 `LlmUnavailableError`→`chat_service` 降级片段摘要（仍 200、`degraded=true`、`model=template`），绝不 500。回滚：改 `.env` 三行切云端，或 `LLM_ENABLED=false` 全量降级 |

- **Ollama 坑**：OpenAI 兼容 `/v1/models` 的模型名字段是 `id`（原生 `/api/tags` 才是 `name`），`probe()` 取值须 `item.get("id") or item.get("name")`，否则误报「在线但无模型」。
- **端口 8000 遗留进程坑**：改动后跑冒烟若命中旧行为（governance 全 stub、`/goods` 404），是上一会话 uvicorn 仍占 8000、新进程静默退出。`Get-NetTCPConnection -LocalPort 8000 -State Listen` 找 OwningProcess 杀掉再重启。
- **文件漂移坑**：本会话多次遇到磁盘版本 ≠ 早先读取版本（用户并行改过 `goods.py` 等）。写文档/断言前用反射（`inspect.signature`）或重读磁盘为准，别信上下文里的旧快照。

- 本机：Python 3.14.5 / Node v22.18.0 / pnpm 12.x（前端 `engines` 要求 Node `>=20.11 <21`，Node 22 只 WARN）。
- 踩过的坑：`requirements.txt` 漏 `python-multipart` → 因 `documents.py` 用 `UploadFile`，FastAPI 在**导入路由阶段**就抛 `RuntimeError` 导致服务起不来。**新增上传/表单端点时必须同步补该依赖。**
- 健康检查：`/health`、`/ready`；无 token 访问 `/api/v1/sessions` 应返回 401（路由级鉴权生效）。

- `.codebuddy/` 下的 `skills/`、`rules/`、`memory/` 都要随仓库提交（不要加进 .gitignore）。
- 有些 AI 工具不认 `.codebuddy/skills`，跨工具需各写一份（`.cursor/rules`、`.github/copilot-instructions.md`、`AGENTS.md`）。

## 本项目既有技能

- `backend-code-style`：FastAPI 分层、统一响应信封 `ok()/fail()`、错误码号段（1xxx 通用 / 2xxx RAG / 3xxx 技能 / 4xxx 任务 / 5xxx 系统）、`governance.access_context()` 租户隔离、降级不 500、smoke 脚本风格。
- `frontend-code-style`：页面方法一律箭头函数、API 层 `src/api/index.ts` 唯一入口、SSE 必带 `Authorization`、Pinia setup 风格、`var(--reai-*)` 设计 token、401 走中央 `handle401()`。
