from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    POSTGRES_USER: str = "edu_user"
    POSTGRES_PASSWORD: str = "edu_password"
    POSTGRES_DB: str = "edu_platform"
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    JWT_ALGORITHM: str = "HS256"

    # LLM
    LLM_BASE_URL: str = "http://host.docker.internal:11434/v1"
    LLM_MODEL: str = "llama3.1"
    LLM_API_KEY: str = "ollama"

    # TTS
    TTS_PROVIDER: str = "silero"
    SILERO_TTS_URL: str = "http://silero-tts:9898"

    # Storage
    STORAGE_PATH: str = "/app/storage"
    BASE_URL: str = "http://localhost:8000"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
