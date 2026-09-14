# 长期记忆（跨会话）

> 只存 `AGENTS.md` / rules / skills 里**没有**的东西：本机环境、复发坑、工具路径、当前进度。
> 前后端红线、质量门禁、设计先行流程一律看 `AGENTS.md`，此处不重复（重复会挤爆记忆并被截断）。

## 项目定位

- 艾梦尔智慧电商 AI 赋能平台 / 多模态智能电商客服系统（Agent + RAG）。文档先行，13 份 root md，索引见 `AGENTS.md` §1。
- ⚠️ 口径冲突：`电商开发文档.md` 自称 FRD v3，其 SSE 仍写旧的 `text/tool_call/tool_result`。**实际形态以 `API接口与SSE事件协议规范.md` §5 的 `source/phase/message/done` 为准。**

## 本机环境与启动

- Python 3.14.5 / Node v22.18.0 / pnpm 12.x（前端 `engines` 要 `>=20.11 <21`，Node 22 只 WARN）。
- 后端 **8000**（`frontend/vite.config.ts` 的 proxy 指向它；`AGENTS.md` 命令速查里的 8010 是错的）；前端 5173。
- 后端：`cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。`.env` 可不建（`Settings` 默认值够用）。
- 默认账号：租户 `demo-tenant` / `admin` / `admin123`（走 `Settings.SEED_*`；**种子不覆盖已存在账号**，老 dev.db 改角色无效，需手动补 roles 或删库重起）。
- 健康检查 `/health` `/ready`；无 token 访问 `/api/v1/sessions` 应 401（路由级鉴权生效）。
- LLM（ADR-0001）：本地 Ollama `qwen2.5:0.5b` @ `http://127.0.0.1:11434/v1`，唯一出口 `app/services/llm_service.py`，`trust_env=False` 防系统代理劫持 localhost；失败收敛 `LlmUnavailableError` → 降级片段摘要，绝不 500。

## 复发坑（动手前先扫一眼）

- **跑测试/探针的输出文件一律写 `$env:TEMP`，禁止落仓库**：`backend/_pytest_out.txt` 被并行窗口的 `git add -A` 扫进索引（状态 `AD`），得 `git rm --cached --ignore-unmatch` 撤出。gitignore 挡不住索引。
- **pytest 汇总行在本机管道里会被吞**（`-q` 明明全过却看不到 `N passed`；另有 GBK `UnicodeDecodeError` 噪声来自 CodeBuddy 的 fs shim）。取得**确定**用例数的可靠姿势：`pytest --junit-xml=_x.xml -q` → 用 Python 解析 `tests/failures/errors/skipped`；或 `Select-Object -Last 3`。
- **`| Select-Object` 会吞掉真实退出码**（管道后 `$LASTEXITCODE` 来自 Select-Object）→ 判断成败要看输出内容或用 `Out-File` 后再读，别只看 exit code。
- **`backend/.pytest-tmp` 全量跑必挂（真因＝中文路径，2026-09-15 定论）**：CodeBuddy fs shim 的 `GetShortPathNameW` 对含中文的路径返回 0 → 清理 basetemp 时 `OSError: [Errno 53]`，表现为**整批 async 测试 setup 全红**（实测 73 errors + pytest exit 3），与代码无关。**可靠解法：`--basetemp="$env:TEMP\pt"` 把 basetemp 挪出中文路径**（`New-Item` 预建 `.pytest-tmp` 无效，别再试）；只跑单个测试文件时可能侥幸不触发，**别据此判绿**。
- **8000 端口被占时先判定归属再动手**：`Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"` 看 `CommandLine`——**命令行带 `--reload` 且父进程也是 python.exe = 用户自己的开发服务，别杀**；我用 `Start-Process` 起的 uvicorn 一定带 `--log-level warning`。端口被占时我的进程会**静默退出**（`Stop-Process` 报 "already gone"），此时冒烟打的是用户的服务（带 reload 会自动加载我的改动，结论仍有效）。
- **`isinstance` 守卫必须与取值同表达式**：`dict(result["k"]) if isinstance(result.get("k"), dict) else {}` 会让 mypy 收窄不传导（`dict(object)` 无匹配重载，报 1 error）。同口径提局部变量即可，勿用 `# type: ignore`。
- **前端手写原生 `<button>` 必须自带 hover + `:focus-visible`**：Element Plus 的焦点环只作用于 EP 组件，`.quick`/`.suggest` 这类自写 button 默认是裸的（`.card`/`.chip` 的 token：`outline: 2px solid var(--reai-primary) + outline-offset: 2px`）。
- **PowerShell / git 中文参数 GBK 乱码**：`git commit -m "中文"`、`git add 中文.md`、`Select-String -Pattern "中文"` 都会坏（2026-09-15 再犯：小提交图省事用 `-m`，subject 在仓库里永久乱码且已 push 无法干净修正）。对策：**中文提交信息一律** `git commit -F`（UTF-8 的 `.git/msg.txt`），无例外；中文文件清单写 `.git/paths.txt` → `git add --pathspec-from-file`；内容探测只用 ASCII 关键字。
- **PowerShell 内联脚本 `$var` 会被吞**（`powershell -Command "foreach($c in ...)"` 报 Missing variable name）→ 批量文本统计改用 `python -c`。
- **并行操作**：用户另一窗口会同时改文件与 `git add -A` / push。断言前重读磁盘，commit 前 `git status --short` 复核 index。实测踩到：按 pathspec 只暂存 7 个文件，`git diff --cached` 却出 83 个（含 `*.pen.bak`）→ `git reset -q` 清索引后重新精确暂存，**每组 commit 前必查 `git diff --cached --name-only`**。2026-09-14 再踩升级版：同窗口并行写**同名共享层**（api/composable/组件），我写的版本被更完整版本覆盖 → **动手写共享层前先 git status + 全文搜索目标名**；被覆盖后以磁盘为准适配视图与测试，不恢复自己的版本。
- **PowerShell 新 shell 坑**：`cd c:\…中文…` 后再执行命令，行尾中文路径最后一字符被 GBK 截断（`;` 被吞）→ 不 cd，直接相对路径执行（初始 cwd 已是工作区根）。
- **git 钩子本机未生效**：`core.hooksPath` 未设，`.git/hooks` 只有 `*.sample` → `frontend/.husky/{pre-commit,commit-msg}`（lint-staged / commitlint）本地不跑，门禁实际只靠 CI。要本地启用：仓库根 `git config core.hooksPath frontend/.husky`。
- **8000 端口遗留进程**：冒烟命中旧行为（governance 全 stub、`/goods` 404）＝旧 uvicorn 仍占端口、新进程静默退出。`Get-NetTCPConnection -LocalPort 8000 -State Listen` 找 PID 杀掉再重启。
- **Ollama 模型名字段**：OpenAI 兼容 `/v1/models` 用 `id`（原生 `/api/tags` 才是 `name`），`probe()` 须 `item.get("id") or item.get("name")`，否则误报「在线但无模型」。
- **`python-multipart`**：新增上传/表单端点必须同步补进 `backend/requirements.txt`，否则 FastAPI 在**导入路由阶段**抛 `RuntimeError`，服务起不来。

## 工具链路径

- 项目级技能 `.codebuddy/skills/<name>/SKILL.md`（**随仓库提交，勿 gitignore**；`skills/` 是源，改完要拷到镜像）；用户级 `C:\Users\qingy\.claude\skills\`；常驻规则 `.codebuddy/rules/*.mdc`（frontmatter：`description` / `alwaysApply` / `enabled`）。
- 跨工具需各写一份（`.cursor/rules`、`.github/copilot-instructions.md`、`AGENTS.md`）。
- **对话框斜杠命令**：项目级 `.codebuddy/commands/<命令名>.md`（用户级 `~/.codebuddy/` 无 commands 目录）。`description` / `argument-hint` 要出现在对话框弹窗里，**frontmatter 必须在第 1 行**——本项目惯例的 `<!-- 职责… -->` 头注释得放在 frontmatter **之后**，否则字段解析不到（命令仍能调起，但弹窗无说明）。子命令想进弹窗＝各写一份短横线命名文件（如 `impeccable-audit.md`，输 `/impeccable` 前缀匹配一起弹），不要指望 `/impeccable audit` 这种空格形式被 IDE 枚举。
- pen.dev schema 离线权威副本：`C:\Users\qingy\.vscode\extensions\highagency.pencildev-0.6.71\out\skills\pen-dev\pen-schema.md`（同目录另有 `SKILL.md` / `execute.md` / `guide/*`；空白模板与示例在 `out/data/*.pen`）。

## design.pen 现状与关键口径（2026-09-14）

- 纯文本 JSON（`version: "2.17"`），顶层 `{version, children[], themes?, variables?}`；**本项目文件无 `variables`/`themes` → 色值全是字面量，切主题只能改字面量**。
- 节点：`frame/text/rectangle/ellipse/path/polygon/icon/note/group/script/ref`。frame 承载 flex（`layout: horizontal|vertical|none`、`gap`、`padding`、`justifyContent`、`alignItems`），尺寸用 `fill_container`/`fit_content`，`cornerRadius` 支持 4 值数组。**text 无 `padding`/`cornerRadius` → 徽标/按钮必须用 frame 包 text**。alpha 只能走 hex alpha 通道 `#RRGGBBAA`。
- **pencil MCP 常连不上**（`transport not connected to app: codebuddy`，扩展侧 IPC，工具侧修不了）→ 降级：直接读写 `.pen` 文本，效果等同，**不得以「连不上」为由跳过设计**。
- **画布打开时改盘有被应用回写覆盖的风险**（实测文件在两次运行间从非法 JSON 变为可解析）→ 改完必须让用户重载画布再继续。
- 画板（2026-09-14 **满覆盖**）：**18/18**，全顶层并列 1280×800，x = 0 → 22780（间距 1340）：`-/workbench -/knowledge -/approvals -/screen -/chat -/tasks -/dashboard -/studio -/admin -/marketing -/logistics -/login -/purchase -/finance -/risk -/goods -/orders -/inventory`。色值全量 `tokens.css` 深色口径；`python scripts/check_design.py` = PASS / ERROR 0 / WARN 0。棘轮：`ROUTE_COVERAGE_MIN=18`（满值，少一张即 CI 红）、`LEGACY_UNNAMED_MAX=0`。**G 步已转常态维护**：后续只有「改 views 必须同改画板」的同改约束，不再有「待出画板」。
- **写盘前必须先读现有顶层画板的 x 分布**（`json.load` 后打印 `name/x/y`）：用户会在 pen.dev 画布上并行新增画板，坐标会撞车 —— 本会话第 2 批原计划 x=9380 起，实读发现 9380~18760 已被用户第 3/4 批占用，改放 20100/21440/22780。
- **批量写画板的省 token 姿势**：临时 Python 生成器（`T/F/chip/bar/field/cell` helper + 色值常量）→ `json.load` → 按 route 幂等替换 `children` → `json.dumps(indent=2, ensure_ascii=False)` → 用完即删。比手搓 JSON 省一大半 token，色值走常量不会漂。
- **`#FFFFFF` 在画板里有两种语义，禁止盲替**：容器面 → `--reai-card #161d33`；彩色底上的白字/白图标 → `#ffffff`。Agent 气泡（`frame` 且 name 含「气泡」且 fill 白）→ `--reai-bubble-agent #f2f5fc`，其子树文字 → `--reai-text-on-light #1f2430`。
- `tokens.css` 已含 3 个语义卡底：`--reai-primary-soft` / `--reai-gold-soft` / `--reai-notice-soft`（12% 叠底）→ 前端实现 VLM 检测卡 / 引用溯源卡 / 预警卡时直接用。
- **`-/workbench` 消息流里的语义卡在画板中是「同级全宽块」**（`VLM检测卡`/`引用溯源卡`/`工具调用卡` 都与 `Agent消息行` 平级、全宽、深底浅字，fill 12% 白 `#FFFFFF1F` + 8% 描边 `#FFFFFF14`）。代码侧现状：VLM/引用卡在**浅气泡内**（存量层级差异，未统一），`ToolCallCard`（2026-09-15 新增）按画板挂在消息行**下方**（`.msgs` 里 `<template>` 包住「消息行+工具卡」）。**新卡一律照画板挂同级；不要塞进浅气泡**（白底上白卡必糊，且改配色＝自创视觉）。
- `check_design.py::norm_color` 已归一到 RGBA（`#rrggbb` / `#rrggbb@aa`），否则 hex-alpha 与 `rgb(… / n%)` 会被误判为不一致。
- 一次性迁移/探针脚本**用完即删**，不给 `design.pen` 留第二事实源。
