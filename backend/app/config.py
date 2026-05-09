from functools import lru_cache
from typing import List

from pydantic import field_validator
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
    LLM_MODEL: str = "qwen3:14b"
    LLM_API_KEY: str = "ollama"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048

    # Vision LLM
    VISION_PROVIDER: str = "ollama"  # ollama | yandex
    VISION_MODEL: str = "qwen2-vl:7b"
    VISION_OLLAMA_BASE_URL: str = "http://host.docker.internal:11434/v1"
    VISION_API_KEY: str = "ollama"

    # Yandex Vision (prod)
    YANDEX_VISION_MODEL: str = "yandexgpt-pro"
    YANDEX_FOLDER_ID: str = ""
    YANDEX_API_KEY: str = ""

    # TTS
    TTS_PROVIDER: str = "silero"
    SILERO_TTS_URL: str = "http://silero-tts:9898"
    SILERO_TTS_VOICE: str = "xenia"

    # Storage
    STORAGE_PATH: str = "/app/storage"
    BASE_URL: str = "http://localhost:8000"

    # CORS — accepts a comma-separated string from env (CORS_ORIGINS=a,b,c) or
    # a JSON array. Use "*" to allow any origin in dev.
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                # JSON array — let pydantic parse it
                return v
            return [s.strip() for s in stripped.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
