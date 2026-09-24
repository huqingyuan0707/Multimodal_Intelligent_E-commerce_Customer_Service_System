"""全局配置（可调全进 Settings，对齐数据模型文档 §配置与热更）

链路：.env → Settings → endpoints/services/适配层只读配置。
"""

from __future__ import annotations

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-only-change-me-and-rotate-in-prod"
# 本地演示种子口令（仅开发用；生产禁用，见 _guard_prod 与 is_default_seed_password）。
_DEFAULT_SEED_PASSWORD = "admin123"


def is_default_seed_password(password: str) -> bool:
    """是否为本地演示默认口令（种子警告与建号拒绝两处共用，禁止生产使用）"""
    return password == _DEFAULT_SEED_PASSWORD


class Settings(BaseSettings):
    """应用配置，禁止业务代码硬编码 URL/密钥/模型名/阈值。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "multimodal-cs"
    # 项目版本唯一口径三源之一（另两源：执行步骤.md 头部版本 / frontend/package.json），
    # 三处必须一致（门禁 scripts/check_version.py），发版 tag 以此为准（release.yml 门禁）。
    APP_VERSION: str = "0.3.27"
    ENV: str = "dev"
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: SecretStr = SecretStr(_DEFAULT_JWT_SECRET)
    VECTOR_DB_URL: str = "http://localhost:6333"
    CORS_ORIGINS: list[str] = []
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # 登录鉴权：Token 有效期/算法、口令哈希代价、角色分隔符、种子账号一律不硬编码（API 规范 §3/§4.1）
    ACCESS_TOKEN_EXPIRE_SECONDS: int = 8 * 3600
    JWT_ALGORITHM: str = "HS256"
    # 注意：改 PASSWORD_HASH_ITERATIONS 会让存量 pwd_hash 全部验不过，必须同步重刷密码。
    PASSWORD_HASH_ITERATIONS: int = 100_000
    PASSWORD_SALT_BYTES: int = 16
    ROLES_SEPARATOR: str = ","
    SEED_ON_START: bool = True
    SEED_TENANT: str = "demo-tenant"
    SEED_USERNAME: str = "admin"
    SEED_PASSWORD: SecretStr = SecretStr(_DEFAULT_SEED_PASSWORD)
    SEED_ROLES: str = (
        "cs,kb,shop,stock,ops,admin,"
        "goods:read,goods:write,stock:read,stock:write,order:read,order:fulfill,"
        "promo:read,promo:write,review:read,review:write,ticket:read,ticket:write,"
        # 经营大屏读权限（screen.py 口径）+ B 端二期（/purchase /finance /risk）读写令牌
        "screen:read,"
        "purchase:read,purchase:write,finance:read,finance:write,risk:read,risk:review,"
        # Agent 工具 Scope（FRDv2 附录 A）：kb.retrieve/refund.create 的 Scope 令牌，
        # 缺了会让客服账号调不动工具（seed 侧只并集补齐，不覆盖存量密码与角色）。
        "kb:read,vision:inspect,trade:refund"
    )

    TOP_K: int = 5  # RAG 热更字段（_HOT_FIELDS 子集，详见 RAG 规范）
    RAG_THRESHOLD: float = 0.6
    # P0 stdlib 双路召回口径（BGE/reranker 接入后调高阈值，业务代码只读 Settings）
    RRF_K: int = 60  # RRF 融合常数
    RAG_DB_THRESHOLD: float = 0.12  # DB 链路余弦相关性下限，低于则拒答
    RAG_DIVERSITY_PER_DOC: int = 2  # 同 doc 至多返回 chunk 数
    KB_CHUNK_CHARS: int = 800  # 单 chunk 上限（主题切分优先，超长才按段硬切）

    # 13 步链路新增可调（上传→解析→向量化→混合检索→Rerank→过滤→拼接→生成→校验→落库→Mining）
    EMB_MODEL: str = "stdlib-hash-64"  # P0 确定性哈希向量；BGE 接入后改名即切
    EMB_DIM: int = 64  # 哈希向量维度（纯 Python 无依赖，万级块毫秒级）
    VECTOR_FUSE_RANK: bool = (
        False  # P0 只索引/打分/上报，不进 RRF（哈希碰撞会扰动排序；BGE 后置 true）
    )
    BGE_RERANKER: str = "rrf-cosine-stub"  # P1 替换为 bge-reranker 模型名
    VECTOR_BACKEND: str = "memory"  # memory/Chroma/pgvector/Milvus（业务只走适配层）
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024  # 单文件上限 5M（超限 1001 中文提示）
    MAX_UPLOAD_CHARS: int = 20000  # 解析截断上限（防超长拖慢切分/提示词）
    RAG_CHANNEL_FILTER: bool = True  # 检索是否按 channels 过滤（渠道隔离）
    FAITHFULNESS_WARN: float = 0.6  # 引用校验低于此值记 guard.pass=False 并进 Mining
    # P1 词汇路升级：TF-IDF 余弦 → BM25（FR-4 混合检索口径；k1/b 热更）
    BM25_K1: float = 1.2
    BM25_B: float = 0.75
    # P1 二阶段精排：RRF/BM25/关键词/向量四特征加权（bge-reranker 替换 rerank 体即可）
    RERANK_W_RRF: float = 1.0
    RERANK_W_BM25: float = 1.0
    RERANK_W_KW: float = 0.5
    RERANK_W_VEC: float = 0.25
    RERANK_TITLE_BONUS: float = 0.15
    # 检索热点缓存：同租户同 query 短 TTL；写操作 bump 语料版本即时失效；0=关闭
    RAG_CACHE_TTL: int = 60
    # 引用统计扫描上限（GET /documents/stats 遍历 messages.citations）
    RAG_STATS_SCAN_LIMIT: int = 5000
    MINING_BAD_VOTE: str = "down"  # 差评口径（进待补知识候选）
    # 高频问聚类：归一化问法 bigram-Dice 相似度≥阈值归一簇；候选池上限防 O(n²) 爆炸
    MINING_CLUSTER_SIM: float = 0.5
    MINING_CLUSTER_POOL: int = 200
    # 对话限流（2002 / 数据模型 §4 rl: 键）：每租户+账号每分钟窗口，计数走 core/cache.py 适配层。
    CHAT_RATE_LIMIT_PER_MIN: int = 30
    _HOT_FIELDS: tuple[str, ...] = (
        "CHAT_RATE_LIMIT_PER_MIN",
        "TOP_K",
        "RRF_K",
        "RAG_DB_THRESHOLD",
        "RAG_DIVERSITY_PER_DOC",
        "KB_CHUNK_CHARS",
        "BM25_K1",
        "BM25_B",
        "RERANK_W_RRF",
        "RERANK_W_BM25",
        "RERANK_W_KW",
        "RERANK_W_VEC",
        "RERANK_TITLE_BONUS",
        "RAG_CACHE_TTL",
        "RAG_STATS_SCAN_LIMIT",
        "MEMORY_SHORT_TTL",
        "MINING_CLUSTER_SIM",
        "LLM_REF_CHARS",
        "LLM_TEMPERATURE",
        "SSE_CHUNK_CHARS",
        "VLM_CONFIDENCE_THRESHOLD",
        "ASR_CONFIDENCE_THRESHOLD",
        "AGENT_TOOL_TIMEOUT_SECONDS",
        "AGENT_TOOL_MAX_RETRIES",
        "AGENT_TOOL_CIRCUIT_THRESHOLD",
        "AGENT_TOOL_CIRCUIT_COOLDOWN_SECONDS",
        "AGENT_CHAT_ORCHESTRATE",
        "GUARD_ENABLED",
        "GUARD_INJECTION_PATTERNS",
        "HANDOFF_ENABLED",
        "HANDOFF_MISS_STREAK_THRESHOLD",
        "HANDOFF_DEGRADE_STREAK_THRESHOLD",
        "HANDOFF_LOAD_LIMIT",
        "OBSERVABILITY_ENABLED",
        "OBSERVABILITY_ANSWER_TARGET_SECONDS",
        "LLM_COST_PER_1K_TOKENS",
        "VLM_COST_PER_IMAGE",
        "ASR_COST_PER_SEC",
        "TTS_COST_PER_CHAR",
        "HUMAN_COST_PER_TICKET_CENTS",
    )

    # 大模型：本地 Ollama（OpenAI 兼容协议 /v1），见 ADR-0001。业务代码只调 llm_service，禁止写地址/模型名。
    LLM_ENABLED: bool = True
    LLM_BASE_URL: str = "http://127.0.0.1:11434/v1"
    LLM_MODEL: str = "qwen2.5:0.5b"
    # Ollama 不校验密钥，此占位仅为满足 OpenAI 协议头；换云端模型时在 .env 覆盖真密钥即可。
    LLM_API_KEY: SecretStr = SecretStr("ollama")
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 512
    # 单条资料进提示词的截断长度（控制本地小模型上下文压力，超长会显著变慢）
    LLM_REF_CHARS: int = 400
    # 模型不可用时降级为「片段摘要」而非 500（AGENTS.md §3 降级红线）
    LLM_FALLBACK_TO_TEMPLATE: bool = True

    # 文本流 message 事件分片长度（增量渲染粒度，大模型按 token 流时再调小）
    SSE_CHUNK_CHARS: int = 120

    # 历史对话三层（FR-1.4）：双重修剪（轮数 + Token 预算）+ 超限摘要压缩 + PII 清洗；阈值只在此。
    SESSION_HISTORY_ROUNDS: int = 20  # 进 LLM 的历史轮数上限（user+agent 算一轮）
    SESSION_TOKEN_BUDGET: int = 8000  # 历史块 Token 预算上限（估算口径见 context_service）
    SESSION_SUMMARY_CHARS: int = 600  # 会话摘要截断长度（sessions.summary）
    SESSION_MSG_CHARS: int = 800  # 单条历史消息进上下文的截断长度

    # 跨会话记忆 FR-4（执行步骤记忆收官）：短期 Redis 24h 滑动 + 长期 PG 偏好（需显式授权）。
    MEMORY_SHORT_TTL: int = 86400  # 短期记忆/线程快照 TTL（秒），每轮回写即滑动续期
    MEMORY_LONG_ENABLED: bool = True  # 长期偏好总开关（False 则只记短期不落 PG）

    # 多模态 FR-1（执行步骤 A）：VLM/ASR/TTS 沿 llm_service 单出口（数据模型 §5 对象存储布局）。
    MEDIA_DIR: str = "./data/media"  # 本地落盘根；s3 模式兼作回读物化缓存根
    MEDIA_BACKEND: str = "local"  # local=本地盘；s3=MinIO/S3（执行步骤 D，数据模型 §5 布局）
    S3_ENDPOINT: str = ""  # 空=AWS 默认端点；MinIO 填 http://minio:9000
    S3_BUCKET: str = "app"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = SecretStr("")
    IMAGE_MAX_COUNT: int = 9  # 单轮附图上限（FR-1.2）
    IMAGE_MAX_BYTES: int = 10 * 1024 * 1024  # 单张 10M，超限 2004 中文拒收
    IMAGE_ALLOWED_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]
    VLM_ENABLED: bool = True
    VLM_BASE_URL: str = "http://127.0.0.1:11434/v1"  # OpenAI 兼容；默认复用 Ollama 位
    VLM_MODEL: str = "qwen2.5:0.5b"  # 有 Qwen3-VL 后 .env 切名即换（FRD §2 选型表）
    VLM_API_KEY: SecretStr = SecretStr("ollama")
    VLM_TIMEOUT_SECONDS: float = 120.0  # 视觉模型首 token 慢，图片推理放宽到 120s
    VLM_MAX_TOKENS: int = 512  # 思考模型 reasoning 占 token，留足避免结论被截断
    VLM_THINK: bool = False  # 思考模型关 thinking 直出 JSON（Ollama 实测有效）
    VLM_PROTOCOL: str = "openai"  # openai（/v1/chat 兼容）| ollama（原生 /api/chat）
    VLM_MAX_EDGE: int = 1280  # 传图前最长边缩放（控 token/延迟，与前端压缩口径同源）
    VLM_JPEG_QUALITY: int = 82  # 缩放后 JPEG 质量（OpenAI image_url 统一转 JPEG）
    VLM_CONFIDENCE_THRESHOLD: float = 0.6  # 低于此值自动转人工复核，不硬答
    ASR_ENABLED: bool = True
    ASR_BASE_URL: str = "http://127.0.0.1:11434/v1"  # SenseVoice 网关封装后切此地址
    ASR_MODEL: str = "sensevoice-small"  # 占位名：网关未接时走转写 stub 降级
    ASR_API_KEY: SecretStr = SecretStr("local")
    ASR_TIMEOUT_SECONDS: float = 30.0
    ASR_CONFIDENCE_THRESHOLD: float = 0.6  # 低置信回问确认，不直接当 query 用
    VOICE_MAX_SECONDS: int = 60  # FR-1.3 录音上限
    VOICE_MAX_BYTES: int = 5 * 1024 * 1024  # 语音 5M，超限 1001 中文拒收
    TTS_ENABLED: bool = True
    TTS_VOICE: str = "晓晓"  # 默认音色（edge-tts 晓晓，FRD §2）
    TTS_VOICES: list[str] = ["晓晓", "云希", "云扬"]  # 可切音色白名单，前端下拉同源

    # 管理后台配额默认（FRD FR-8 / 数据模型 §2 tenants.quota_*）：新建租户落库口径，.env 可覆盖。
    DEFAULT_QUOTA_TOKENS: int = 1000000
    DEFAULT_QUOTA_CONCURRENCY: int = 50
    TENANT_PLANS: list[str] = ["trial", "basic", "pro", "enterprise"]

    # API 密钥（FR-8 密钥管理）：明文只在创建/轮换响应里回一次，落库只存 sha256 摘要。
    # 明文形态 `<prefix>_<token_urlsafe(API_KEY_BYTES)>`；列表掩码保留正文首尾各 MASK_KEEP 位。
    API_KEY_PREFIX: str = "sk_live"
    API_KEY_BYTES: int = 18
    API_KEY_MASK_KEEP: int = 4
    API_KEY_SCOPES_DEFAULT: str = "read"

    # 消息发送频控（FR-12.2）：同一 user_ref 在 WINDOW 秒内最多 MAX 条，计数走 core/cache.py 适配层。
    NOTIFY_RATE_MAX: int = 1
    NOTIFY_RATE_WINDOW_SECONDS: int = 86400

    # Agent Runtime / 工具注册中心（FRD FR-3/FR-5）：超时/重试/熔断进 Settings（_HOT_FIELDS 可热更）。
    AGENT_TOOL_TIMEOUT_SECONDS: float = 30.0  # 附录 A：单次工具调用超时 30s
    AGENT_TOOL_MAX_RETRIES: int = 3  # 仅幂等安全方法自动重试（非幂等恒 1 次）
    AGENT_TOOL_CIRCUIT_THRESHOLD: int = 3  # 连续失败达此值即开闸（熔断）
    AGENT_TOOL_CIRCUIT_COOLDOWN_SECONDS: int = 60  # 开闸后冷却秒数，到点半开试探
    AGENT_TOOL_RETRY_BACKOFF_SECONDS: float = 0.2  # 重试间隔（按第 n 次线性放大）
    AGENT_MAX_STEPS: int = 4  # 单轮规划最多执行步数（防编排空转）
    AGENT_CHAT_ORCHESTRATE: bool = (
        True  # /chat 检索段走 Agent 编排；false 一键回退直调 knowledge_service
    )

    # 外部 Agent（office-agent 开源仓库）拉取出口：/api/v1/agent-gateway/*
    # 口径（方案 §7 数据不出域）：对端就是一个普通登录用户，不新造信任体系——
    #   · 入口权限走既有 require_perm（角色即权限），令牌名在此声明不散落端点；
    #   · X-On-Behalf-Of 只被白名单主体采纳，其余一律忽略并告警（防伪造发起人）；
    #   · 凭据（服务账号口令/令牌）只走环境变量或建号脚本，绝不进配置与库。
    OFFICE_AGENT_GATEWAY_PERM: str = "agent:gateway"
    OFFICE_AGENT_SERVICE_ACCOUNTS: list[str] = []  # 可透传 X-On-Behalf-Of 的服务账号名（默认空=不采纳）
    # 服务账号建号默认角色（scripts/create_service_account.py 用；读工具 Scope 缺一不可）
    # ticket:write 是联动模式②（office 审批通过后回流建单）的写入口径——审批闸门在对端，
    # 本侧只认 Scope + idem_key 幂等回放；存量账号需 --reset 补角色才会拿到。
    OFFICE_AGENT_SERVICE_ROLES: str = (
        "svc,order:read,stock:read,promo:read,kb:read,ticket:write,agent:gateway"
    )

    # 转人工触发规则表（FRD FR-7）：「什么时候该转人工」的唯一口径在 handoff_rules.py 规则表，
    # 词表与阈值在此；挂载点只有 handoff_service.auto_handoff()（对话落库 / Agent 编排共用）。
    HANDOFF_ENABLED: bool = (
        True  # 总开关：false 时规则表不判命，仅显式动作（买家点转人工/坐席认领）改流转态
    )
    HANDOFF_HUMAN_KEYWORDS: list[str] = ["人工", "真人", "转客服", "找客服", "客服电话"]
    HANDOFF_ANGRY_KEYWORDS: list[str] = [
        "投诉",
        "差评",
        "曝光",
        "举报",
        "315",
        "骗人",
        "垃圾",
        "气死",
        "太差",
    ]
    HANDOFF_MISS_STREAK_THRESHOLD: int = (
        3  # 「3 次不懂」：连续未解决轮次达此值即转人工（0/负数=关闭该规则）
    )
    HANDOFF_DEGRADE_STREAK_THRESHOLD: int = 3  # 模型连续降级达此值即转人工（0/负数=关闭该规则）
    # 技能组路由与负载均衡（FRD FR-7「技能组 + 负载均衡」）：
    # 规则表每条规则挂一个组（general=通用，任何坐席可接）；坐席技能组走
    # users.roles 的 `cs:<组>` 令牌（admin/* 恒全组）；assign 智能分配按
    # 「技能匹配 + 在手 < 上限 + 最少者优先」，上限 0=关闭分配只留手动抢接。
    HANDOFF_SKILL_GROUPS: list[str] = ["general", "refund", "complaint", "aftersale"]
    HANDOFF_LOAD_LIMIT: int = 5  # 单坐席在手（handling）会话上限，assign 用（0=关闭）

    # 质检打分与绩效（FRD FR-7「质检打分」/ 执行步骤 C 步收官）：resolve 会话后台
    # LLM-as-judge 自动评分（模型不可用走规则兜底），坐席可人工改评（source=manual）。
    QUALITY_AUTO_SCORE: bool = True  # 解决会话后自动评分总开关（false=只留手动）
    QUALITY_PASS_SCORE: int = 4  # 绩效口径：综合分 ≥ 此值算质检通过（1..5）
    QUALITY_MAX_MESSAGES: int = 40  # 送 judge 的会话消息上限（超长截断，控 token 成本）

    # 输入域守卫（guard_service，问答第一道闸）：注入模式 + 电商客服域词表。
    # 词表可热更；误拦率优先于拦全率——拿不准一律放行给 RAG 治理兜底。
    GUARD_ENABLED: bool = True  # false=整体旁路（回滚位，同 AGENT_CHAT_ORCHESTRATE）
    # 成本单价（元/单位），用于 cost_cents 折算（_HOT_FIELDS 可热更，生产按真实报价填）
    # LLM: 元/千 tokens（prompt+completion 分开算更精准，暂按总量均价）
    LLM_COST_PER_1K_TOKENS: float = 0.002
    VLM_COST_PER_IMAGE: float = 0.005  # VLM: 元/张图
    ASR_COST_PER_SEC: float = 0.001  # ASR: 元/秒音频
    TTS_COST_PER_CHAR: float = 0.0001  # TTS: 元/字符
    # 人工单通成本基线（分/通，默认 ¥15）：单会话成本对照的分母，生产按财务口径覆盖；
    # 归因误差度量 = 估算单占比（pricing_source=estimate 的费用占比，越低越准）
    HUMAN_COST_PER_TICKET_CENTS: int = 1500
    # 域外黑名单：确定与电商客服无关的闲聊/套话/越权话题词，命中即拒（先于白名单；
    # 只收无歧义词，宁可少拦不误伤——域内无据由检索阈值负责拒答）
    GUARD_OFF_DOMAIN_KEYWORDS: list[str] = [
        "天气",
        "股票",
        "股价",
        "基金",
        "电影",
        "电视剧",
        "笑话",
        "驾照",
        "八字",
        "算命",
        "星座",
        "加油站",
        "好吃",
        "菜谱",
        "做什么菜",
        "训练数据",
        "system prompt",
        "代码",
        "编程",
        "翻译",
        "闲聊",
        "推荐一部",
        "附近",
        "怎么治",
        "求职信",
        "讲个",
        "量子",
        "算法原理",
        "竞争对手",
        "黑进",
        "密码",
        "密钥",
        "手机号",
        "别的店铺",
        "其他店铺",
        "内部角色",
        "买家群",
        "盗版",
        "jailbreak",
        "脏话",
        "脏字",
        "你是谁",
        "注册资本",
        "扮演",
        "免审批",
        "现在几点",
    ]
    GUARD_INJECTION_PATTERNS: list[str] = [
        r"忽略(以上|之前|所有)(的)?(指令|提示|规则)",
        r"无视(租户隔离|权限|风控|安全)",
        r"(system|系统)?\s*prompt",
        r"(api|访问|数据库)?\s*密钥",
        r"越权",
        r"扮演\s*\w",
        r"假设你是.{0,6}(管理员|监管|root|超级|平台)",
        r"我是.{0,8}(监管|管理员|平台).{0,10}(免审|直接|批准)",
        r"(绕过|绕开)风控",
        r"伪造.{0,6}(截图|凭证|单据)",
        r"(别的|其他|其它)买家.{0,4}(手机号|电话|信息)",
        r"(其他|别的|其它)租户.{0,6}(数据|尺码表|订单|资料)",
        r"(其他|别的|其它)店铺.{0,6}(政策|价格|资料|数据)",
        r"(内部|机密).{0,8}(发给|发到|泄漏|外传|群)",
        r"(全部|所有)(内部|机密)(资料|文件|密码)",
        r"批量.{0,4}(下单|注册)",
        r"黑进|入侵|攻击账号",
        r"(从现在开始|从现在起).{0,10}(脏|无视|没有(任何)?限制)",
        r"没有任何限制",
    ]

    # 可观测（FRD FR-9 / 执行步骤 E 步）：关键链路事件 → core/observability.py
    # 内存计数器 + JSONL 落盘（Prometheus/Langfuse 网关后置替换只改该模块）。
    OBSERVABILITY_ENABLED: bool = True  # false=只留内存态不落盘（record 仍即时计数）
    OBSERVABILITY_DIR: str = "./data/observability"  # 本地事件目录；接网关后此口径退役
    OBSERVABILITY_ANSWER_TARGET_SECONDS: int = 30  # 接起率目标（FR-7 验收「30s 内接起」）

    # B 端业务阈值（数据模型文档 §2.1 / API 规范 §4.7）：金额一律整数「分」，禁浮点。
    B2B_SEED_DEMO: bool = True  # 演示数据（商品/仓库/库存/订单），生产置 false
    KB_SEED_DEMO: bool = True  # 企业知识库种子（docs/knowledge-base 29 篇），生产置 false
    KB_SEED_DIR: str = "docs/knowledge-base"  # 相对仓库根；镜像内无此目录时跳过
    STOCK_WARN_DEFAULT: int = 10  # 新建库存行的默认安全线
    REFUND_APPROVAL_LIMIT_CENTS: int = 10000  # 退款超此金额（100 元）恒进审批（3003）
    FINANCE_DIFF_WARN_CENTS: int = 5000  # 对账差异告警线（/finance 红字，超 50 元才亮）
    APPROVAL_SLA_HOURS: int = 24  # 审批超时升级线：待办等待超此时长即标超期（红标 + 只看超期筛选）
    # 物流单号格式（打单发货校验，非法返回 1001）：8~24 位字母数字
    TRACKING_NO_PATTERN: str = r"^[A-Za-z0-9]{8,24}$"
    # 经营大屏（screen_service）红线：退货率超此比值即亮 bad 预警（0.08 = 8%）
    SCREEN_RETURN_WARN_RATIO: float = 0.08
    # 快递公司白名单（发货校验 + 物流公司列表唯一口径，8 家全量；order/logistics 双服务同源）
    LOGISTICS_COMPANIES: list[str] = [
        "顺丰",
        "中通",
        "圆通",
        "韵达",
        "申通",
        "京东",
        "邮政",
        "德邦",
    ]

    @model_validator(mode="after")
    def _guard_prod(self) -> Settings:
        """生产护栏（fail-fast）：ENV=prod 禁默认密钥、禁一切演示种子，配置错即启动失败。

        宁可起不来，也不要带 demo 密钥/账号/演示数据上生产（AGENTS.md §3）；首个管理员走
        scripts/create_admin.py 创建，不经过 SEED_* 演示通道。
        """
        if self.ENV != "prod":
            return self
        secret = self.JWT_SECRET.get_secret_value()
        if secret == _DEFAULT_JWT_SECRET or len(secret) < 32:
            raise ValueError("生产环境必须显式设置 JWT_SECRET 且不少于 32 字符")
        if self.SEED_ON_START:
            raise ValueError("生产环境必须设 SEED_ON_START=false，种子账号仅用于开发演示")
        if self.B2B_SEED_DEMO:
            raise ValueError("生产环境必须设 B2B_SEED_DEMO=false，演示商品/订单不得进生产库")
        if self.KB_SEED_DEMO:
            raise ValueError("生产环境必须设 KB_SEED_DEMO=false，演示知识不得进生产库")
        return self


settings = Settings()
