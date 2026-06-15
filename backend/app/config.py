from functools import lru_cache
from typing import List, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# SECRET_KEY values shipped in templates / earlier defaults. Allowed in dev (so
# `cp .env.example .env` still boots), rejected when ENVIRONMENT=production.
_WEAK_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "change-me",
        "your-super-secret-key-change-in-production",
        "CHANGE_ME_OPENSSL_RAND_HEX_32",
    }
)
_MIN_SECRET_KEY_LENGTH: int = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    POSTGRES_USER: str = "edu_user"
    POSTGRES_PASSWORD: str = "edu_password"
    POSTGRES_DB: str = "edllm"
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT — required (no default). pydantic-settings fails fast at boot if unset,
    # so the app can never sign forgeable tokens with a known key. It also signs
    # email-verify tokens and HMAC /files/* URLs (see signed_url_service).
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    REFRESH_TOKEN_ABSOLUTE_MAX_DAYS: int = 90
    # Sliding-window TTL (in days) when remember_me=False on login.
    REFRESH_TOKEN_SESSION_DAYS: int = 1

    # LLM
    LLM_BASE_URL: str = "http://host.docker.internal:11434/v1"
    LLM_MODEL: str = "qwen3:8b"
    LLM_API_KEY: str = "ollama"
    LLM_TEMPERATURE: float = 0.7
    # Cap for enhance_lecture_text and the vision narration calls. Raised for the
    # cloud move so a long enhanced lecture / 150-300-word slide narration is not
    # truncated. It's a ceiling, not a target — no cost increase unless the model
    # actually emits more. The SSML split (_chat) sets no max_tokens on purpose,
    # so a many-slide chunk array can't be truncated by this setting.
    LLM_MAX_TOKENS: int = 4096
    # Polza/OpenRouter upstream-provider pin for the text model. Comma-separated
    # display names (e.g. "StreamLake" or "StreamLake,SiliconFlow"); the first
    # available serves the request, allow_fallbacks rolls to the next on
    # outage/incompatibility. Blank → the gateway chooses. Empty by default so
    # plain Ollama (the local default) never receives the unknown field.
    LLM_PROVIDER_ORDER: str = ""

    # Model used to refine vision output during single-slide regeneration.
    # Defaults to the same text LLM as LLM_MODEL; set independently if you
    # want a different model for the polish pass (e.g. qwen3:8b vs a heavier model).
    REGEN_LLM_MODEL: str = "qwen3:8b"

    # Vision LLM
    VISION_PROVIDER: str = "ollama"  # ollama | yandex
    VISION_MODEL: str = "qwen2-vl:7b"
    VISION_OLLAMA_BASE_URL: str = "http://host.docker.internal:11434/v1"
    VISION_API_KEY: str = "ollama"
    # Suppress hidden chain-of-thought on reasoning-capable models (Qwen 3.6 etc.)
    # via the OpenRouter-style `reasoning: {enabled: false}` body param. Off by
    # default: the param is not part of the core OpenAI schema, so it is only
    # sent when explicitly enabled for a provider that understands it (Polza).
    VISION_REASONING_DISABLED: bool = False
    # Polza/OpenRouter upstream-provider pin for the vision model — same format
    # and semantics as LLM_PROVIDER_ORDER. allow_fallbacks is essential here: not
    # every provider under a multimodal model actually accepts image_url, so a
    # blind pin could break generation; the fallback rolls to a working one.
    VISION_PROVIDER_ORDER: str = ""

    # Yandex Vision (prod)
    YANDEX_VISION_MODEL: str = "yandexgpt-pro"
    YANDEX_FOLDER_ID: str = ""
    YANDEX_API_KEY: str = ""

    # Email — transactional mail (verification, video-ready). Sent only from the
    # send_email Celery task. Provider is pluggable; Resend is implemented today.
    EMAIL_PROVIDER: str = "resend"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "Edllm <no-reply@edllm.app>"
    # Public origin of the SPA — used to build verify/redirect/lesson links.
    FRONTEND_URL: str = "http://localhost:3000"

    # TTS
    TTS_PROVIDER: str = "silero"
    SILERO_TTS_URL: str = "http://silero-tts:9898"
    SILERO_TTS_VOICE: str = "xenia"

    # polza.ai TTS gateway (OpenAI-compatible POST /audio/speech) — active when
    # TTS_PROVIDER=polza, running openai/tts-1. The endpoint returns JSON with
    # base64 audio (mp3), which tts_service transcodes to WAV via ffmpeg.
    POLZA_API_KEY: str = ""
    POLZA_BASE_URL: str = "https://api.polza.ai/v1"
    POLZA_TTS_MODEL: str = "openai/tts-1"
    # Fallback voice when the requested one is not in POLZA_TTS_VOICES
    # (constants.py). Must itself be a valid openai/tts-1 voice.
    POLZA_DEFAULT_VOICE: str = "nova"
    # Optional speech speed for openai/tts-1 (0.25–4.0). None = not sent, the
    # provider default (1.0) applies. Tuning lives here, not inline.
    POLZA_TTS_SPEED: float | None = None
    POLZA_TIMEOUT: float = 120.0
    # TTS thread-pool size when TTS_PROVIDER=polza. Silero's TTS_WORKERS=4 is
    # tied to the local container's thread count; the cloud gateway is bounded
    # by its own rate limits instead, so the pool is tunable per deployment.
    POLZA_TTS_WORKERS: int = 4

    # Billing admin — shared secret for /api/v1/billing/admin/* endpoints,
    # checked against the X-Admin-Token header. Empty disables admin access.
    ADMIN_API_TOKEN: str = ""

    # YooKassa — one-time credit-package payments. Empty SHOP_ID/SECRET_KEY
    # disables payment creation (POST /billing/payments returns 503). The
    # webhook authenticates by re-fetching the payment from the YooKassa API,
    # not by trusting the request body. API URL is overridable for tests.
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3"
    # Where YooKassa redirects the buyer after checkout. Empty falls back to
    # f"{FRONTEND_URL}/billing".
    YOOKASSA_RETURN_URL: str = ""
    # 54-ФЗ receipts (ИП): when True, payment creation includes a receipt block
    # (customer email + one "Пакет N кредитов" item with this vat_code).
    YOOKASSA_SEND_RECEIPT: bool = False
    YOOKASSA_VAT_CODE: int = 1

    # Storage
    STORAGE_PATH: str = "/app/storage"
    BASE_URL: str = "http://localhost:8000"
    STORAGE_BACKEND: Literal["local", "s3"] = "local"

    # Static file delivery (local backend only).
    # False (dev): FastAPI serves /files/* itself (StaticFiles-equivalent).
    # True  (prod): nginx serves /files/* directly from disk; FastAPI only
    #   exposes the internal auth_request verify endpoint.
    SERVE_STATIC_VIA_NGINX: bool = False
    # Public base URL signed /files/* links point at — the nginx/CDN domain in
    # prod. Empty falls back to BASE_URL so dev links keep working unchanged.
    PUBLIC_FILES_BASE_URL: str = ""

    # S3-compatible storage (Yandex Object Storage, AWS S3, MinIO, …)
    S3_ENDPOINT_URL: str = "https://storage.yandexcloud.net"
    S3_BUCKET_NAME: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_REGION: str = "ru-central1"
    S3_PRESIGNED_URL_EXPIRE_SECONDS: int = 3600

    # Signed URLs (HMAC-protected /files/*). Lifetime, in seconds.
    # Per-content overrides (video/slide) are in constants.py; this value is
    # the env-override cap / fallback for uncategorised files.
    SIGNED_URL_EXPIRES_IN: int = 1800

    # In-memory slide-PNG cache (TTLCache). Keyed by MD5+DPI of the source file.
    SLIDES_CACHE_TTL_SECONDS: int = 86400
    SLIDES_CACHE_MAX_SIZE: int = 256

    # Cookies
    COOKIE_SECURE: bool = False      # set True in production (HTTPS only)
    COOKIE_SAMESITE: str = "Lax"    # Lax works with same-origin dev proxy

    # Sentry
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"
    APP_VERSION: str = "dev"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    # Run `alembic upgrade head` inside the FastAPI lifespan on startup.
    # True (dev): convenient auto-migrate on `docker-compose up`.
    # False (prod): migrations are a separate one-shot deploy step (the
    # `migrate` service), so a heavy or failing migration can't take the app
    # down on boot and gunicorn's N workers don't each race to upgrade.
    RUN_MIGRATIONS_ON_STARTUP: bool = True

    # Flower — Celery monitoring UI
    CELERY_FLOWER_USER: str = "admin"
    CELERY_FLOWER_PASSWORD: str = "change-me"

    # Metrics
    METRICS_ENABLED: bool = True

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

    @model_validator(mode="after")
    def _validate_production_secret(self) -> "Settings":
        """In production, reject a blank, placeholder, or too-short SECRET_KEY.

        SECRET_KEY is already required everywhere (no default), so this only
        adds a prod guard against shipping a template placeholder. Dev keeps the
        permissive behavior so `cp .env.example .env` boots without edits.
        """
        if self.ENVIRONMENT == "production":
            key = self.SECRET_KEY.strip()
            if not key or key in _WEAK_SECRET_KEYS or len(key) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    "SECRET_KEY must be a strong, non-default value "
                    f"(>= {_MIN_SECRET_KEY_LENGTH} chars) when ENVIRONMENT=production"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def provider_routing(order: str) -> dict:
    """OpenRouter-style provider-routing fragment for the Polza gateway.

    `order` is a comma-separated list of provider display names; the first
    available one serves the request, with allow_fallbacks so a down or
    incompatible provider rolls to the next instead of failing. Blank → {}
    (let the gateway pick). Only Polza/OpenRouter understand this field, so
    callers gate on a non-empty result before adding it to extra_body — plain
    Ollama/Yandex must not receive it.
    """
    names = [p.strip() for p in order.split(",") if p.strip()]
    if not names:
        return {}
    return {"provider": {"order": names, "allow_fallbacks": True}}
