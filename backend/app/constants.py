# TTS
SILERO_MAX_CHARS: int = 800  # conservative limit: Silero returns 500 on very long inputs
# polza.ai caps the openai/tts-1 `input` at 4096 chars (probed 2026-06-10: longer
# → 400). Stay under with margin; still far above Silero's 800 → fewer audible seams.
POLZA_MAX_CHARS: int = 4000
# Transient polza failures (429/5xx/timeout) are retried with exponential backoff;
# other 4xx (bad key, bad voice) fail fast. Mirrors LLM_MAX_RETRIES below.
POLZA_TTS_MAX_RETRIES: int = 3
# openai/tts-1 voice catalog accepted by polza (probed 2026-06-10: these 9 → 200,
# "ballad"/"verse" → 400). Single source of truth: the API voice validator
# (schemas/lesson.py) and the polza synth fallback both build on this. The
# frontend dropdown sends one of these names directly — no name translation.
POLZA_TTS_VOICES: tuple[str, ...] = (
    "alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer",
)
TTS_CACHE_TTL_DAYS: int = 7

# Slide rendering
SLIDE_DPI: int = 150  # indistinguishable from 300 DPI on 1080p, 4× smaller PNGs

# Upload limits
MAX_SCRIPT_BYTES: int = 10 * 1024 * 1024  # 10 MB
# Ready-made video uploaded directly to a lesson (no generation pipeline).
MAX_VIDEO_UPLOAD_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB

# Assignment attachments (teacher-set text tasks + student submissions). Files
# are only STORED, never parsed server-side (avoids XXE/zip-bomb from office
# docs). These are the hard ceilings; per-assignment max_files / max_file_mb /
# allowed_ext are validated to stay within them.
ASSIGNMENT_MAX_FILES: int = 10                 # ceiling on files per submission
ASSIGNMENT_MAX_FILE_MB: int = 25               # ceiling on per-file size (MB)
ASSIGNMENT_MAX_FILE_BYTES: int = ASSIGNMENT_MAX_FILE_MB * 1024 * 1024
ASSIGNMENT_DEFAULT_MAX_FILES: int = 5
ASSIGNMENT_DEFAULT_MAX_FILE_MB: int = 10
# Extension whitelist (lower-case, no dot). A per-assignment allowed_ext must be
# a subset of this; uploads are checked against the per-assignment list.
ASSIGNMENT_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "csv", "txt", "md", "rtf", "odt", "png", "jpg", "jpeg", "gif", "zip",
)
ASSIGNMENT_DEFAULT_MAX_POINTS: float = 100.0
ASSIGNMENT_MAX_PROMPT_CHARS: int = 20000
ASSIGNMENT_MAX_TEXT_CHARS: int = 50000         # student answer body / teacher feedback
ASSIGNMENT_MAX_MESSAGE_CHARS: int = 4000       # one private-thread message

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
# Anti-abuse caps for the FREE LLM grading of students' open answers. Teachers
# are never metered. An open answer longer than the char cap is rejected with a
# 422 before any LLM call; more than N graded submissions per quiz per day per
# student is a 429. Enforced in routers/quiz_student.submit_attempt.
GRADING_MAX_ANSWER_CHARS: int = 2000
GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY: int = 5

# Billing / credits
# Per-operation credit cost for FLAT-priced operations. Video generation is
# priced by formula instead — see VIDEO_*_BASE_CREDITS below and
# billing_service.estimate_video_text/estimate_video_auto.
CREDIT_WEIGHTS: dict[str, int] = {
    "vision_analyze": 5,    # vision-анализ PPTX → SlideText (без видео)
    "slide_regen": 1,       # регенерация одного слайда через vision LLM
    "quiz_generate": 5,     # AI-генерация квиза (полная цена и при перегенерации)
    "ai_review": 2,         # AI-review вопросов квиза
    "quiz_grade": 0,        # AI-проверка квиза — бесплатно (маркетинговый аргумент)
}

# Video-generation pricing formula components (polza.ai tariffs of 2026-06-11,
# upper bound: TTS 1380.48 ₽/1M chars; qwen3-30b 17.49 ₽/1M prompt / 63.5 ₽/1M
# completion tokens). Credits formula:
#   text mode: VIDEO_TEXT_BASE + slides + ceil(script_chars / TTS_CHARS_PER_CREDIT)
#   auto mode: VIDEO_AUTO_BASE + slides + ceil(slides * AUTO_CHARS_PER_SLIDE / TTS_CHARS_PER_CREDIT)
VIDEO_TEXT_BASE_CREDITS: int = 2
VIDEO_AUTO_BASE_CREDITS: int = 3
TTS_CHARS_PER_CREDIT: int = 3000
AUTO_CHARS_PER_SLIDE: int = 600  # нормативная длина озвучки слайда в auto-режиме

# Provider cost rates (rubles) for the generation_usage margin journal.
TTS_RUB_PER_MCHAR: float = 1380.48
LLM_RUB_PER_MTOK_PROMPT: float = 17.49
LLM_RUB_PER_MTOK_COMPLETION: float = 63.5

# Lifetime trial for free accounts: usage_counters(period_key='lifetime').
# A trial lecture/quiz is consumed instead of credits while slots remain.
TRIAL_LECTURES: int = 2
TRIAL_QUIZZES: int = 2
TRIAL_MAX_SLIDES: int = 20          # cap per trial lecture
TRIAL_MAX_SCRIPT_CHARS: int = 15000  # cap per trial lecture (text mode)

# Tariff plans. Keys match CreditPlan enum values. Free accounts get no welcome
# credits — the lifetime trial (2 lectures + 2 quizzes) replaces them.
PLAN_CONFIGS: dict[str, dict[str, int]] = {
    "free":    {"monthly_allowance": 0,   "onetime_credits": 0,  "price_rub": 0},
    "starter": {"monthly_allowance": 30,  "onetime_credits": 0,  "price_rub": 490},
    "pro":     {"monthly_allowance": 120, "onetime_credits": 0,  "price_rub": 1490},
    "school":  {"monthly_allowance": 500, "onetime_credits": 0,  "price_rub": 4990},
}

# One-time credit packages purchasable via YooKassa. Keys are package_key in
# POST /api/v1/billing/payments and Payment.package_key.
CREDIT_PACKAGES: dict[str, dict[str, int]] = {
    "pack_50":   {"credits": 50,   "price_rub": 190},
    "pack_200":  {"credits": 200,  "price_rub": 590},
    "pack_500":  {"credits": 500,  "price_rub": 1290},
    "pack_1200": {"credits": 1200, "price_rub": 2690},
}

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
