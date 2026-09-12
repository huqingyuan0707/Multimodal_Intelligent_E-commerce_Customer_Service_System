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
    SEED_ROLES: str = "cs,kb"

    # RAG 热更字段（_HOT_FIELDS 子集，详见 RAG 规范）
    TOP_K: int = 5
    RAG_THRESHOLD: float = 0.6

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
