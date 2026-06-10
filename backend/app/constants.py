# TTS
SILERO_MAX_CHARS: int = 800  # conservative limit: Silero returns 500 on very long inputs
# polza.ai /audio/speech hard-caps `input` at 5000 chars; stay under with margin.
# Deliberately much higher than Silero's limit: fewer chunks → fewer audible seams.
POLZA_MAX_CHARS: int = 4500
# Transient polza failures (429/5xx/timeout) are retried with exponential backoff;
# other 4xx (bad key, bad voice) fail fast. Mirrors LLM_MAX_RETRIES below.
POLZA_TTS_MAX_RETRIES: int = 3
# Frontend voice values (Silero names) → ElevenLabs premade voice names on polza
# (polza addresses voices by name, not voice_id). Unknown names fall back to
# settings.POLZA_DEFAULT_VOICE.
POLZA_VOICE_MAP: dict[str, str] = {
    "xenia": "Sarah",        # жен.
    "baya": "Alice",         # жен.
    "kseniya": "Charlotte",  # жен.
    "aidar": "Daniel",       # муж.
    "eugene": "George",      # муж.
}
TTS_CACHE_TTL_DAYS: int = 7

# Slide rendering
SLIDE_DPI: int = 150  # indistinguishable from 300 DPI on 1080p, 4× smaller PNGs

# Upload limits
MAX_SCRIPT_BYTES: int = 10 * 1024 * 1024  # 10 MB
# Ready-made video uploaded directly to a lesson (no generation pipeline).
MAX_VIDEO_UPLOAD_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB

# Soft delete
# How long a soft-deleted (archived) record lingers before the daily
# purge_soft_deleted Celery task physically removes it and its files.
SOFT_DELETE_PURGE_DAYS: int = 30

# Worker concurrency
TTS_WORKERS: int = 4     # matches NUMBER_OF_THREADS in silero-tts docker-compose service
ENCODE_WORKERS: int = 3  # concurrent FFmpeg processes; leaves headroom for LO and TTS threads

# ── LLM / vision provider request tuning ─────────────────────────────────────
# Cloud providers (Polza AI, Yandex AI Studio) add network latency and enforce
# rate limits, unlike a local Ollama pinned to the host CPU. Give requests a
# finite wall clock and let the OpenAI SDK retry transient failures with its
# built-in exponential backoff: it retries 429/408/409/>=500/timeout and honours
# Retry-After. 401/403 (bad key) are NOT retried by the SDK — they fail fast and
# surface to the per-slide handler, which logs and (when every slide fails) marks
# the lesson `error`.
LLM_REQUEST_TIMEOUT_SECONDS: float = 120.0
LLM_MAX_RETRIES: int = 3
VISION_REQUEST_TIMEOUT_SECONDS: float = 180.0  # base64 images → heavier requests
VISION_MAX_RETRIES: int = 3
# Parallel vision-summary calls (the alignment-hint pass). Bounded to stay under
# provider rate limits.
VISION_SUMMARY_CONCURRENCY: int = 4

# Quiz
QUIZ_PASS_THRESHOLD: float = 0.6  # default for new quizzes; per-quiz override in Quiz.pass_threshold
QUIZ_NUM_QUESTIONS: int = 5
QUIZ_NUM_OPTIONS: int = 4
QUIZ_MIN_QUESTIONS: int = 1
QUIZ_MAX_QUESTIONS: int = 20
QUIZ_DEFAULT_WEIGHT: float = 1.0
QUIZ_LLM_TEMPERATURE: float = 0.2
QUIZ_LLM_OPEN_MAX_TOKENS: int = 400
QUIZ_MAX_MATERIAL_CHARS: int = 12000
# Parallel LLM-IO grading of open answers — bounded by upstream LLM throughput.
QUIZ_GRADING_WORKERS: int = 4

# Billing / credits
# Per-operation credit cost. Keys are matched by callers via CREDIT_WEIGHTS["..."].
CREDIT_WEIGHTS: dict[str, int] = {
    "lesson_generate": 10,  # PPTX→видео полный цикл (vision+LLM+TTS+FFmpeg)
    "lesson_regen": 8,      # повторная генерация (кеш слайдов есть, но LLM+TTS+FFmpeg)
    "vision_analyze": 5,    # vision-анализ PPTX → SlideText (без видео)
    "slide_regen": 1,       # регенерация одного слайда через vision LLM
    "quiz_grade": 0,        # AI-проверка квиза — бесплатно (маркетинговый аргумент)
}

# Tariff plans. Keys match CreditPlan enum values.
PLAN_CONFIGS: dict[str, dict[str, int]] = {
    "free":    {"monthly_allowance": 0,   "onetime_credits": 50, "price_rub": 0},
    "starter": {"monthly_allowance": 30,  "onetime_credits": 0,  "price_rub": 490},
    "pro":     {"monthly_allowance": 120, "onetime_credits": 0,  "price_rub": 1490},
    "school":  {"monthly_allowance": 500, "onetime_credits": 0,  "price_rub": 4990},
}

TOPUP_PACKS: list[dict[str, int]] = [
    {"credits": 50,  "price_rub": 750},
    {"credits": 200, "price_rub": 2600},
]

CREDIT_CARRYOVER_RATIO: float = 0.5  # до 50% месячного объёма переносится на след. месяц

# ── Celery scheduling priority by tier ───────────────────────────────────────
# A "tier" (free|paid|enterprise) is DERIVED from the billing CreditPlan via
# PLAN_TIER_MAP — there is no separate tier column. Its only role is the priority
# at which a user's Celery jobs are scheduled (paid ahead of free). Spend itself
# is governed by credits, not quotas. enterprise is groundwork: highest priority,
# but no current CreditPlan maps to it (no separate logic/UI yet).

# CreditPlan value → tier. Keys match CreditPlan/PLAN_CONFIGS; unknown → "free".
PLAN_TIER_MAP: dict[str, str] = {
    "free":    "free",
    "starter": "paid",
    "pro":     "paid",
    "school":  "paid",
}

# Celery scheduling priority per tier (passed to apply_async(priority=...)).
# IMPORTANT — Redis broker semantics: a LOWER number is HIGHER priority (0 is
# drained first, 9 last). This is the REVERSE of RabbitMQ. Verified against the
# Celery routing docs ("In Redis, priority 0 is considered the highest priority,
# while priority 9 is the lowest"). Hence enterprise=0 (highest), free=9 (lowest).
# Values must fall inside broker_transport_options["priority_steps"] in
# app/celery_app.py (currently 0..9).
TIER_PRIORITY: dict[str, int] = {
    "free":       9,
    "paid":       3,
    "enterprise": 0,
}

# Default question-type distribution for quiz generation.
# Keys match the type strings used in generate_quiz_v2 / _parse_payload_v2.
# Fractions must sum to 1.0; short_answer absorbs rounding remainders.
QUIZ_TYPE_DISTRIBUTION: dict[str, float] = {
    "single_choice": 0.50,
    "multiple_choice": 0.30,
    "true_false": 0.10,
    "short_answer": 0.10,
}
# Below this count the distribution is skipped and all questions are single_choice.
QUIZ_MIN_FOR_DISTRIBUTION: int = 4

# Email
# Lifetime of the signed email-verification token (itsdangerous max_age).
EMAIL_VERIFICATION_TTL_SECONDS: int = 60 * 60 * 24  # 24h
# Min seconds between two resend-verification requests for the same user
# (Redis cooldown, enforced on top of the slowapi per-IP limit).
EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS: int = 60
# send_email Celery task retry policy on retriable provider failures.
EMAIL_SEND_MAX_RETRIES: int = 3
EMAIL_SEND_RETRY_BACKOFF: int = 5  # base seconds; Celery grows it exponentially

# Access code generation
ACCESS_CODE_LENGTH: int = 6
# No I, O, 1, 0 — visually ambiguous characters excluded.
ACCESS_CODE_ALPHABET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCESS_CODE_MAX_RETRIES: int = 10
