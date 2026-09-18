# D 步「生产存储切换」收口方案（库存预占 + MinIO/S3 + PostgreSQL）

## Context（为什么做这件事）

`执行步骤.md` §D 把当前焦点定为「生产存储切换（PostgreSQL / MinIO / Redis 原子扣减）」——把「本机可跑」推成「生产可信」的最后一公里。开工前实测，现状与任务清单并不一致，实际缺口如下：

| 任务清单项 | 实测状态 |
| --- | --- |
| 库存预占服务（预占/释放/确认 + DB 双写） | **代码已写但未提交**（`git status` 显示 `M backend/app/services/inventory_service.py`、`M backend/app/core/cache.py`），且把 `inventory_service.py` 撑到 **584 行**，超出 `check_arch.py` 棘轮预算 425 → **门禁当前是红的** |
| 库存预占端点 | 已在位（`endpoints/inventory.py` 的 `/inventory/reserve`、`/reserve/release`、`/reserve/confirm`） |
| API 规范同步 | 已在位（`API接口与SSE事件协议规范.md` §4.7 L126 已完整描述三端点与 Redis Lua 闸门） |
| 并发零超卖验证 | **缺失**：`backend/tests/` 无任何并发预占用例 |
| MinIO/S3 对象存储 | **完全未做**：`media_store.py` 仅本地盘（77 行），`config.py` 无任何 S3 配置，`requirements.txt` 无对象存储依赖 |
| PostgreSQL | **未接线**：`requirements.txt` 缺 `asyncpg`；`docker-compose.prod.yml`（19 行）只覆盖环境变量，无任何 PG/Redis/MinIO 服务定义 |
| 门禁全绿 | **当前不绿**：`check_arch.py` FAIL（1 new violation） |

另发现一处**缺陷**：`core/cache.py::stock_sync()`（自愈对齐闸门，注释写明「供库存变更后自愈对齐，如出入库/盘点」）**全仓库无任何调用点**，是死代码。后果是 Redis 闸门只在首次预占时以 `base_available` 初始化，此后每次入库/出库/盘点都不回写，闸门会长期停在旧值。该偏差方向是「误拒」而非「超发」（DB 行锁是第二道防线仍会兜底），但会让「库存账实一致 ≥99.5%」的验收口径失真。本方案一并收口。

**已确认的四个决策**（用户已选）：prod compose 一次接齐 **PG + MinIO + Redis**；预占三函数**拆出 `reserve_service.py`**（不动棘轮）；S3 客户端用 **boto3**；S3 模式回读采用**物化到本地缓存后返回 Path**（`resolve_path` 签名与读端点零改动）。

**范围红线**：不做 SQLite → PG 的列类型迁移（`String` 存 uuid / `Text` 存 JSON 在 PG 上行为等价，是当前「dev 用 SQLite、prod 用 PG、同一套 schema」设计的支点；改原生 UUID/JSONB 会直接打断 dev/test）。PG 侧只做「驱动 + 接线 + 迁移实跑核对」。

---

## 变更一：库存预占收口（拆文件 + 闸门自愈 + 并发验证）

### 1.1 拆出 `backend/app/services/reserve_service.py`（新建）

把三个预占函数从 `inventory_service.py` 原样迁出：`reserve_capacity` / `release_reserve` / `confirm_reserve`。

- 单向依赖：`reserve_service` → `inventory_service`（不反向，无循环导入）。
- 需要复用的私有件**提升为公开名**（否则跨模块 import 私有符号）：`_stock_key` → `stock_key`、`_warehouse_or_raise` → `warehouse_or_raise`，同步改 `inventory_service` 内部调用点。
- 头 docstring 按后端 Skill §2 写「职责 + 链路 + 对齐章节」，引用数据模型 §4 `stock:{tenant}:{warehouse}:{sku}`。

### 1.2 再拆出 `backend/app/services/stocktake_service.py`（新建）

仅拆预占**不足以**回到预算内（584 − 151 ≈ 433 > 425），且 1.3 的自愈接线还要加行。故把「盘点/差异生效/补货」这一同生命周期家族一并外迁：`stocktake` / `apply_stocktake` / `replenish`。两条边界语义清晰：**预占生命周期** vs **盘点补货生命周期**，与上轮「采购拆 `supplier_service`」同一手法。

`apply_stocktake` 由 `approval_service` 的处理器按名引用，迁走只需改 import。

预期结果：`inventory_service.py` ≈ 320 行（余量充足，不再每次改都顶线）。

### 1.3 闸门自愈接线（关掉死代码）

在 `move_stock` 的 `in` / `out` / `move`（含目标仓）分支与 `apply_stocktake` 落库后调用 `cache.stock_sync(stock_key(...), qty, reserved, locked)`，与 DB 的 `qty/reserved/locked` 对齐。实现落在拆分后的 `reserve_service.py`（`move_stock` 就在该文件内），一处口径。

### 1.4 并发零超卖验证（新建 `backend/tests/test_stock_reserve.py`）

夹具沿用 `tests/test_biz_ops.py` 的口径（monkeypatch `settings.DATABASE_URL` → `tmp_path` 文件库、`session_mod._engine = None`、`init_models()`、`async_sessionmaker(expire_on_commit=False)`），并调用既有的 `cache.reset()` 清内存闸门保证用例隔离。

用例：

1. `test_gate_concurrent_no_oversell`（**确定性**）：`base_available=10`，`asyncio.gather` 并发 50 次 `cache.stock_reserve(key, 1, base_available=10)`，断言恰好 10 次 True。直接证明闸门原子性。
2. `test_concurrent_reserve_no_oversell`：库存 10，并发 20 次 `reserve_capacity(qty=1)`，断言成功恰好 10 次、失败全部为 `3004`，且终态 `reserved == 10`、`available == 0`。
   - SQLite 并发写会锁库，夹具内用 `event.listens_for(engine.sync_engine, "connect")` 设 `PRAGMA busy_timeout` / `journal_mode=WAL`（**仅测试本地**，不动 `app/db/session.py`），避免 flaky。
   - 因闸门先拦掉 10 个，实际只有 10 个事务进 DB。
3. 生命周期：`reserve 5 → release 3 → confirm 2`，断言 `qty/reserved/available` 与 `kind="out"` 的 `StockMove` 落行。
4. 边界：超量释放 `3004`、可确认预占不足 `3004`。
5. `test_gate_selfheal_after_inbound`：入库后闸门被 `stock_sync` 对齐，新库存可被预占（覆盖 1.3）。

---

## 变更二：MinIO/S3 对象存储后端

### 2.1 `backend/app/config.py`（新增配置，**须守住 400 行硬线**）

`config.py` 当前**恰好 400 行**且未列入 `FILE_LINE_BUDGET`，加字段必超线。做法：新增字段的同时**等量压缩现有冗余注释**，净值 ≤ 400（该文件历史上已用此手法控行）。

新增字段：

```
MEDIA_BACKEND: str = "local"        # local | s3
S3_ENDPOINT_URL: str = ""           # MinIO/OSS 端点；留空走 AWS 默认
S3_BUCKET: str = ""
S3_REGION: str = "us-east-1"
S3_ACCESS_KEY: str = ""
S3_SECRET_KEY: SecretStr = SecretStr("")
S3_PREFIX: str = ""                 # 对象键前缀（可选）
```

### 2.2 `backend/app/services/media_store.py`（保持签名不变）

**公开签名零改动**：`save_upload(*, tenant, kind, session_id, filename, raw) -> dict`、`resolve_path(*, tenant, file_id) -> Path | None`。

- 后端分派读 `settings.MEDIA_BACKEND`；boto3 **惰性 import**，local 模式不需要该依赖。
- `_s3_client()`：惰性单例 + 双检锁（与 `session.py` / `cache.py` 同写法）。
- 对象键对齐数据模型 §5：`{S3_PREFIX}{tenant}/%Y/%m/{session_id}/{file_id}{ext}`。
- `save_upload`：local 走原逻辑；s3 走 `put_object`，`path` 返回 `s3://{bucket}/{key}`（调用方只消费 `file_id/url`，`path` 未被业务使用，已核对）。
- `resolve_path`：local 走原逻辑；s3 把对象下载到 `{MEDIA_DIR}/_s3cache/...` 后返回该 `Path`；对象不存在返回 `None`（读端点 404 语义不变，`FileResponse` 调用点零改动）。
- `status()`：新增，镜像 `cache.status()` 形状（`backend` / `available` / `degraded` / `bucket` / `root`），供治理巡检。
- **写失败不静默回退**：s3 模式下 `put_object` 失败若回退本地盘，对象将不可被 `resolve_path`（s3 模式只查 S3）读回，造成「存得进、读不出」。故上传失败**显式抛业务错误**（映射到 5xxx 系统错误码，落现有 `ErrorCode` 号段，不产生裸 500）；`status()` 里 `degraded` 可见。

### 2.3 治理巡检接线

`GET /governance/status`（`endpoints/governance.py`）加 `media: media_store.status()` 一项，并把该文件与 `数据模型/API 规范` 里「七适配层」改为「八适配层」。

### 2.4 依赖

`backend/requirements.txt` 加 `boto3>=1.35`。

---

## 变更三：PostgreSQL 接线

1. **驱动**：`backend/requirements.txt` 加 `asyncpg>=0.30`（运行时，对应 `postgresql+asyncpg://`）。`psycopg2-binary` 已在 `requirements-dev.txt`（alembic 同步迁移用），不动。
2. **`docker-compose.prod.yml`**（现 19 行）：新增 `postgres`（postgres:16-alpine + 数据卷 + healthcheck）、`redis`（redis:7-alpine + healthcheck）、`minio`（minio/minio + 数据卷 + healthcheck）；`backend` 增补 `DATABASE_URL=postgresql+asyncpg://…`、`REDIS_URL`、`MEDIA_BACKEND=s3` 与 `S3_*`，并 `depends_on` 各服务 `condition: service_healthy`；末尾补 volumes。保留既有 prod 覆盖（`ENV=prod`、三种子全关、`JWT_SECRET` fail-fast）。
3. **`docker-compose.yml`（dev 基线）不动**：本地演示继续 SQLite + 本地盘。
4. **迁移核对（真跑，不只是离线编译）**：起一次性 PG 容器（`docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=… postgres:16-alpine`）→ `DATABASE_URL=postgresql+asyncpg://… alembic upgrade head` → `alembic check` → 核对四表与索引落库、单头 `a1b2c3d4e5f6`。若镜像拉取不可用，退回 CI 已有的 PG 方言离线出 SQL（`alembic upgrade head --sql`）并如实标注未实跑。

> 说明：CI（`.github/workflows/ci.yml` L69-79）已有 `alembic upgrade head` + `alembic check` + PG 方言离线编译三步，本步补的是**真连 PG 实跑**这一缺口。

---

## 变更四：门禁与文档、版本、记忆

**版本升 `0.3.27`**（三源同改，`scripts/check_version.py` 校验）：`执行步骤.md` 头部、`frontend/package.json`、`backend/app/config.py::APP_VERSION`。

**文档同改**（AGENTS.md §5 联动规则）：

- `API接口与SSE事件协议规范.md`：多模态媒体章节补 `MEDIA_BACKEND` 与「读端点与存储后端无关」；`/governance/status` 补 `media` 字段、七→八适配层。
- `数据模型与存储设计.md`：§5 对象存储补「MinIO/S3 已落地 + 物化读缓存 + 键布局」；§4 补闸门随库存变更自愈（`stock_sync`）一条。
- `部署工程化.md`：§六 补 PG/MinIO/Redis 的 prod compose 接线与 `asyncpg` 驱动。
- `执行步骤.md`：头部版本与变更行；§D L192 把「**余**库存预占原子扣减」划掉并补 MinIO/S3、PG 接线、闸门自愈；现状盘点表同步。

**记忆写入**：把本版决策与「config.py 顶 400 行线时用压缩注释腾行」「拆 service 守棘轮而非上调预算」「S3 写失败不回退」等口径写入项目记忆。

---

## 验证（每步贴真实命令输出，不写「应该过了」）

```bash
# 后端起服务与单测
cd backend
python -m py_compile app/services/reserve_service.py app/services/stocktake_service.py app/services/media_store.py app/config.py
ruff check . ; ruff format --check .
mypy app
pytest tests/test_stock_reserve.py -q          # 并发零超卖
pytest -q                                      # 全量不回归

# 结构与体量硬线（本次重点：必须由红转绿）
python ../skills/anti-shit-code/scripts/check_arch.py .
#   期望：PASS，inventory_service.py 回到 425 预算内；新增文件均 ≤400

# 版本与文档门禁
python ../scripts/check_version.py --root ..
python ../scripts/check_docs_link.py
python ../scripts/check_design.py

# PG 真跑迁移
docker run --rm -d --name reai-pg -p 55432:5432 -e POSTGRES_PASSWORD=reai postgres:16-alpine
DATABASE_URL="postgresql+asyncpg://postgres:reai@127.0.0.1:55432/postgres" alembic upgrade head
DATABASE_URL="postgresql+asyncpg://postgres:reai@127.0.0.1:55432/postgres" alembic check
# 核对四表/索引落库后 docker stop reai-pg

# compose 配置可解析
docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# S3 模式自检（MinIO 容器起来后）
#   MEDIA_BACKEND=s3 + S3_* 指向容器 → 上传 → GET /api/v1/multimodal/media/{file_id} 回读 200
#   GET /governance/status 的 media.backend == "s3"
```

**验收对照**（`执行步骤.md` §D）：并发下单超卖率 = 0（用例 1/2 实证）；跨租户 0 串数（`resolve_path` 租户前缀不变，沿用既有断言）。