"""全局配置（可调全进 Settings，对齐数据模型文档 §配置与热更）

链路：.env → Settings → endpoints/services/适配层只读配置。
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，禁止业务代码硬编码 URL/密钥/模型名/阈值。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "multimodal-cs"
    ENV: str = "dev"
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: SecretStr = SecretStr("dev-only-change-me")
    VECTOR_DB_URL: str = "http://localhost:6333"
    CORS_ORIGINS: list[str] = []
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # RAG 热更字段（_HOT_FIELDS 子集，详见 RAG 规范）
    TOP_K: int = 5
    RAG_THRESHOLD: float = 0.6


settings = Settings()
