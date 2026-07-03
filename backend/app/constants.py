from app.config import settings

# Signed URL lifetimes (seconds). SIGNED_URL_EXPIRES_IN in config.py is the
# env-override cap for uncategorised files; these per-type values are tighter.
# Videos need to outlive a full viewing session; slides only need to cover the
# duration of an active editor session.
SIGNED_URL_TTL_VIDEO: int = 1800   # 30 min
SIGNED_URL_TTL_SLIDE: int = 600    # 10 min

# Video streaming delivery — see the /stream endpoints in routers/lessons.py.
# The endpoint authorises the request, then delegates the actual byte transfer
# so Python never streams the MP4 in prod:
#   * S3 (primary): 302 → short-lived presigned URL; the browser streams from S3.
#   * local + nginx: empty body + X-Accel-Redirect to the internal prefix below;
#     nginx serves the file (Range/sendfile). Tracks SERVE_STATIC_VIA_NGINX so it
#     is on wherever nginx fronts the app (prod) and off in dev.
#   * local + no nginx (dev): 302 → signed absolute /files URL. Dev serializers
#     also hand the player that signed URL directly (video_playback_url), so the
#     cross-origin <video> loads bytes straight from the backend instead of
#     through the same-origin proxy, which can't relay a streamed 206.
# The prefix is aliased to the storage root by nginx:
#   location /protected-media/ { internal; alias /var/www/storage/; }
VIDEO_XACCEL_ENABLED: bool = settings.SERVE_STATIC_VIA_NGINX
VIDEO_XACCEL_INTERNAL_PREFIX: str = "/protected-media/"
# <video> re-requests ranges directly against the presigned URL, so the TTL must
# outlive a full viewing session — a short TTL would break seeking on long
# lessons. Trade-off: within the TTL the URL is a bearer capability (un-enrolling
# a student does not revoke an already-issued URL until it expires).
S3_PRESIGN_TTL_SECONDS: int = 6 * 3600  # 6h — covers a long lesson + seeking

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

# Chunk-level TTS disk cache (tts_service, keyed on _split_for_tts output). This
# is finer-grained than the whole-slide cache in tasks/video_pipeline.py: a
# single edited sentence in a long script only re-synthesizes its own chunk
# instead of invalidating the whole slide's cached audio.
TTS_CHUNK_CACHE_ENABLED: bool = True
TTS_CHUNK_CACHE_DIR_NAME: str = "tts_chunk_cache"

# Slide rendering
SLIDE_DPI: int = 150  # indistinguishable from 300 DPI on 1080p, 4× smaller PNGs

# Upload limits
MAX_SCRIPT_BYTES: int = 10 * 1024 * 1024  # 10 MB
# Hard cap on the DECOMPRESSED size of an uploaded .docx (a zip package).
# MAX_SCRIPT_BYTES only bounds the compressed upload; a small zip whose parts
# inflate to gigabytes (zip-bomb) would still OOM the parser. python-docx pins
# lxml with resolve_entities=False (no XXE / billion-laughs), so this is the
# remaining DoS vector — checked in uploads._extract_docx_text before parsing.
MAX_DECOMPRESSED_DOCX_BYTES: int = 100 * 1024 * 1024  # 100 MB
# Ready-made video uploaded directly to a lesson (no generation pipeline).
MAX_VIDEO_UPLOAD_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB

# Assignment attachments (teacher-set text tasks + student submissions). Files
# are only STORED, never parsed server-side (avoids XXE/zip-bomb from office
# docs). Students may attach anything on the whitelist (incl. video), but a
# submission is capped by file count, per-category file size, and total bytes.
# These are SYSTEM limits (storage-cost guard) — not configurable per assignment.
# The load-bearing guards are the whitelist + ATTACHMENT_MAX_FILES +
# ATTACHMENT_MAX_TOTAL_SIZE_MB; the per-category caps are secondary (clear
# messages and keeping a "document" from being gigantic).
ATTACHMENT_MAX_FILES: int = 10                 # max files per submission (per kind)
ATTACHMENT_MAX_TOTAL_SIZE_MB: int = 1024       # max combined size of one submission
# Per-file ceiling by category (MB): video is generous, documents/images small.
ATTACHMENT_CATEGORY_MAX_SIZE_MB: dict[str, int] = {
    "document": 50,
    "image": 50,
    "audio": 200,
    "video": 500,
    "archive": 200,
}
# Whitelist — MIME type → category. Source of truth for what may be attached;
# the category drives the per-file size limit above.
ATTACHMENT_ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "text/plain": "document",
    "text/markdown": "document",
    "text/csv": "document",
    "application/rtf": "document",
    "application/vnd.oasis.opendocument.text": "document",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/heic": "image",
    "image/gif": "image",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "application/zip": "archive",
    "application/x-zip-compressed": "archive",
}
# Extension → MIME fallback when the client omits or forges Content-Type. An
# extension absent here is rejected outright (defends a spoofed MIME riding on a
# disallowed extension, e.g. ".exe" sent as image/png).
ATTACHMENT_EXTENSION_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "heic": "image/heic",
    "gif": "image/gif",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "zip": "application/zip",
}
# Retention: submission attachment files are auto-purged this many days after the
# submission's grade is finalized (see purge_pipeline). Storage-cost guard — the
# grade/feedback rows are kept, only the stored files + their records go.
ATTACHMENT_RETENTION_DAYS_AFTER_GRADED: int = 30
# Extension whitelist (lower-case, no dot) for the teacher-set per-assignment
# allowed_ext filter — separate from the system attachment whitelist above.
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

# ── Periodic disk GC (tasks/purge_pipeline.gc_disk_caches / gc_lesson_videos) ──
# Reclaims disk the soft-delete purge never touches: the two reproducible
# content-hash caches, and stale UNPUBLISHED LessonVideo re-gen versions.
#
# Recency for cache eviction is the FS mtime we bump on every cache HIT
# (os.utime), NOT atime — containers run relatime/noatime so atime never
# advances on read and an atime-LRU would evict the hottest entries. Both bounds
# apply per cache: hard-TTL evicts anything unused that long, then a size cap
# trims the least-recently-used until the cache fits. Caches are always local
# (never S3) and fully reproducible — a deleted entry just forces a re-render.
CACHE_GC_ENABLED: bool = True                   # kill-switch for the cache GC pass only
SLIDES_CACHE_TTL_DAYS: int = 30                 # slides_cache/<hash>/ dirs unused this long → evict
SLIDES_CACHE_MAX_BYTES: int = 5 * 1024**3       # 5 GiB cap (rendered PNGs are large)
SUMMARIES_CACHE_TTL_DAYS: int = 60              # .txt summaries: LLM-costly to redo → keep longer
SUMMARIES_CACHE_MAX_BYTES: int = 512 * 1024**2  # 512 MiB cap

# LessonVideo GC has its OWN kill-switch (separate from the caches): deleting a
# video version is IRREVERSIBLE, whereas a cache entry is reproducible — on an
# incident you want to disable video pruning without losing the disk-reclaim
# that may be the thing keeping storage from filling. NEVER deletes an
# is_published=True version, and always keeps the newest KEEP_UNPUBLISHED
# unpublished per lesson (a lesson is never left with zero videos).
LESSON_VIDEO_GC_ENABLED: bool = True            # kill-switch for the LessonVideo GC pass only
LESSON_VIDEO_UNPUBLISHED_TTL_DAYS: int = 30     # cold unpublished versions eligible after this
LESSON_VIDEO_KEEP_UNPUBLISHED: int = 2          # newest N unpublished per lesson always survive

# Startup reconciliation: lessons stuck in non-terminal status (analyzing /
# processing) for longer than this window are presumed to have lost their Celery
# task (Redis flushdb or crash without AOF) and are marked error on backend
# startup. Must exceed the worst-case pipeline runtime so that legitimately
# in-flight tasks during a rolling restart are not disturbed.
STUCK_LESSON_GRACE_MINUTES: int = 120

# Worker concurrency
TTS_WORKERS: int = 4     # matches NUMBER_OF_THREADS in silero-tts docker-compose service
ENCODE_WORKERS: int = 3  # concurrent FFmpeg processes; leaves headroom for LO and TTS threads

# Segment encoding (still-image slide + narration audio). All segments must use
# identical params — concatenate_segments joins them with `-c copy` (no re-encode).
SEGMENT_FPS: int = 5                  # slide is static; 25fps was pure waste
SEGMENT_AUDIO_BITRATE: str = "96k"    # mono narration doesn't need 192k
SEGMENT_AUDIO_CHANNELS: int = 1
SEGMENT_KEYFRAME_SECONDS: int = 2     # keyframe every ~2s keeps in-slide seeking smooth

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
# default for new quizzes; per-quiz override in Quiz.pass_threshold
QUIZ_PASS_THRESHOLD: float = 0.6
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
#
# Each package also carries its 54-ФЗ receipt attributes, used only when
# YOOKASSA_SEND_RECEIPT is on (services/yookassa_service._receipt):
#   vat_code        — НДС-код из «Справочника значений» ЮKassa для 54-ФЗ
#       (https://yookassa.ru/developers/payment-acceptance/receipts/54fz/parameters-values#vat-codes).
#       ВНИМАНИЕ: с 2026-01-01 базовая ставка НДС — 22%; конкретные коды для
#       пакетов обязательно согласовать с бухгалтером. Здесь значение-заглушка
#       (1 = «НДС не облагается»).
#   payment_subject — предмет расчёта (service = услуга)
#   payment_mode    — признак способа расчёта (full_payment = полный расчёт)
CREDIT_PACKAGES: dict[str, dict[str, str | int]] = {
    "pack_50":   {"title": "50 кредитов",   "credits": 50,   "price_rub": 190,  "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"},  # noqa: E501
    "pack_200":  {"title": "200 кредитов",  "credits": 200,  "price_rub": 590,  "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"},  # noqa: E501
    "pack_500":  {"title": "500 кредитов",  "credits": 500,  "price_rub": 1290, "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"},  # noqa: E501
    "pack_1200": {"title": "1200 кредитов", "credits": 1200, "price_rub": 2690, "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"},  # noqa: E501
}

CREDIT_CARRYOVER_RATIO: float = 0.5  # до 50% месячного объёма переносится на след. месяц

# YooKassa HTTP client (services/yookassa_service.py). One AsyncClient per
# process; retries cover ONLY network/timeout errors of idempotent calls
# (POST /payments rides the same Idempotence-Key, GET re-fetch is idempotent) —
# 4xx is never retried. Backoff grows as YOOKASSA_RETRY_BACKOFF * 2**attempt.
YOOKASSA_CONNECT_TIMEOUT: float = 5.0
YOOKASSA_READ_TIMEOUT: float = 20.0
YOOKASSA_MAX_RETRIES: int = 2
YOOKASSA_RETRY_BACKOFF: float = 0.5  # base seconds

# Webhook hardening (routers/billing.yookassa_webhook + services/webhook_security).
# The notification body is never trusted (the payment is re-fetched), but as
# defence in depth we also reject calls whose real client IP is outside the
# published YooKassa ranges. These CIDRs are an OVERRIDABLE FALLBACK — the
# authoritative source is the YooKassa docs / SDK SecurityHelper:
# https://yookassa.ru/developers/using-api/webhooks#ip
YOOKASSA_TRUSTED_CIDRS: tuple[str, ...] = (
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",
    "77.75.156.35/32",
    "77.75.154.128/25",
    "2a02:5180::/32",
)
# The only hops that may legitimately sit between YooKassa and the backend are
# the loopback / private docker network and the prod nginx. X-Forwarded-For is
# honoured ONLY when the immediate TCP peer is one of these — never blindly.
YOOKASSA_TRUSTED_PROXIES: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)
# Notification events the webhook acts on; anything else is acknowledged (200)
# and ignored so YooKassa stops retrying.
YOOKASSA_HANDLED_EVENTS: frozenset[str] = frozenset(
    {
        "payment.succeeded",
        "payment.waiting_for_capture",
        "payment.canceled",
        "refund.succeeded",
    }
)
# Settlement is money-critical and low-volume → schedule it at the highest
# Celery priority (0 = first on the Redis broker, see TIER_PRIORITY below).
PAYMENT_TASK_PRIORITY: int = 0
# The webhook returns 200 immediately, so YooKassa won't redeliver — the task's
# own retries are the backstop for a transient YooKassa outage (the poll path is
# the other). More attempts over a longer window than the HTTP-level retries.
PAYMENT_TASK_MAX_RETRIES: int = 5
PAYMENT_TASK_RETRY_BACKOFF: float = 10.0  # base seconds; grows as base * 2**retries
PAYMENT_TASK_RETRY_MAX_BACKOFF: float = 300.0  # cap a single wait at 5 min

# Reconcile sweep (tasks/payment_pipeline.reconcile_pending_payments). Catches
# payments stuck in `pending` when the webhook 200'd but the settle task never
# ran (Redis blip) AND the user never polled. Runs on beat in celery_quiz →
# queue `quiz`. Reuses the SAME settlement path, so it can't double-credit.
RECONCILE_INTERVAL_MINUTES: int = 15      # beat cadence
RECONCILE_MIN_AGE_MINUTES: int = 10       # grace: let the task + poll settle first
RECONCILE_MAX_AGE_HOURS: int = 72         # stop re-querying long-dead payments
RECONCILE_BATCH_SIZE: int = 100
# Alert when a payment is STILL pending past this despite reconcile — exactly
# once per payment (Payment.alerted_at). Email is optional and OFF by default
# (structured ERROR log → Sentry is always on); needs config.ALERT_ADMIN_EMAIL.
PAYMENT_STUCK_ALERT_MINUTES: int = 60
PAYMENT_STUCK_ALERT_BATCH: int = 50
PAYMENT_STUCK_ALERT_EMAIL: bool = False

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

# Password reset
# Lifetime of a one-time password-reset token (DB-backed, only its hash is
# stored). Kept short — long enough to receive and click the email, no more.
PASSWORD_RESET_TTL_SECONDS: int = 60 * 30  # 30 min
# Entropy of the raw reset token (bytes handed to secrets.token_urlsafe).
PASSWORD_RESET_TOKEN_BYTES: int = 32
# SPA route that consumes the reset token; the raw token is appended as ?token=.
PASSWORD_RESET_PATH: str = "/reset-password"

# Registration consents (personal-data processing)
# Version of the legal documents the user is consenting to at registration time.
# Bump this whenever the privacy policy / terms change so we can tell which
# revision each user agreed to.
CONSENT_POLICY_VERSION: str = "2026-07-01"

# Access code generation
ACCESS_CODE_LENGTH: int = 6
# No I, O, 1, 0 — visually ambiguous characters excluded.
ACCESS_CODE_ALPHABET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCESS_CODE_MAX_RETRIES: int = 10
