"""全局配置（可调全进 Settings，对齐数据模型文档 §配置与热更）

链路：.env → Settings → endpoints/services/适配层只读配置。
"""

from __future__ import annotations

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-only-change-me-and-rotate-in-prod"


class Settings(BaseSettings):
    """应用配置，禁止业务代码硬编码 URL/密钥/模型名/阈值。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "multimodal-cs"
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
    SEED_PASSWORD: SecretStr = SecretStr("admin123")
    SEED_ROLES: str = (
        "cs,kb,shop,stock,ops,admin,"
        "goods:read,goods:write,stock:read,stock:write,order:read,order:fulfill,"
        "promo:read,promo:write,review:read,review:write,ticket:read,ticket:write"
    )

    # RAG 热更字段（_HOT_FIELDS 子集，详见 RAG 规范）
    TOP_K: int = 5
    RAG_THRESHOLD: float = 0.6

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

    # 管理后台配额默认（FRD FR-8 / 数据模型 §2 tenants.quota_*）：新建租户落库口径，.env 可覆盖。
    DEFAULT_QUOTA_TOKENS: int = 1000000
    DEFAULT_QUOTA_CONCURRENCY: int = 50
    TENANT_PLANS: list[str] = ["trial", "basic", "pro", "enterprise"]

    # B 端业务阈值（数据模型文档 §2.1 / API 规范 §4.7）：金额一律整数「分」，禁浮点。
    B2B_SEED_DEMO: bool = True  # 演示数据（商品/仓库/库存/订单），生产置 false
    STOCK_WARN_DEFAULT: int = 10  # 新建库存行的默认安全线
    REFUND_APPROVAL_LIMIT_CENTS: int = 10000  # 退款超此金额（100 元）恒进审批（3003）
    # 物流单号格式（打单发货校验，非法返回 1001）：8~24 位字母数字
    TRACKING_NO_PATTERN: str = r"^[A-Za-z0-9]{8,24}$"
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
        """生产护栏：ENV=prod 时禁默认密钥、禁自动灌种子，配置错就启动即失败（fail-fast）。

        宁可起不来，也不要带着 demo 密钥/账号上生产（对齐 AGENTS.md §3 安全红线）。
        """
        if self.ENV != "prod":
            return self
        secret = self.JWT_SECRET.get_secret_value()
        if secret == _DEFAULT_JWT_SECRET or len(secret) < 32:
            raise ValueError("生产环境必须显式设置 JWT_SECRET 且不少于 32 字符")
        if self.SEED_ON_START:
            raise ValueError("生产环境必须设 SEED_ON_START=false，种子账号仅用于开发演示")
        return self


settings = Settings()
