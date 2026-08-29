import os

from app.config import settings

# Signed URL lifetimes (seconds). SIGNED_URL_EXPIRES_IN in config.py is the
# env-override cap for uncategorised files; these per-type values are tighter.
# Videos need to outlive a full viewing session; slides only need to cover the
# duration of an active editor session.
SIGNED_URL_TTL_VIDEO: int = 1800  # 30 min
SIGNED_URL_TTL_SLIDE: int = 600  # 10 min
# Knowledge-base material downloads: long enough for a big handout to finish
# downloading, short enough that a copied link dies quickly.
SIGNED_URL_TTL_MATERIAL: int = 900  # 15 min

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
# SpeechKit API v1 caps the POST body at 15 KB; URL-encoded Cyrillic is ~3x its
# character count, so chunks stay far below the documented 5000-char limit.
YANDEX_TTS_MAX_CHARS: int = 200  # v3 hard-caps ~250 chars/request; kept under with margin
YANDEX_TTS_MAX_RETRIES: int = 3
# Fixed sentence for the "preview this voice" sample in the generation form —
# short enough to stay under every provider's per-chunk cap above.
TTS_SAMPLE_TEXT: str = "Это пример голоса для озвучки вашего урока."
# Ceiling for a pause translated from <break time="..."/> into sil<[ms]> — an LLM
# that emits time="60s" must not stall a slide for a minute.
YANDEX_TTS_MAX_PAUSE_MS: int = 5000
# Ranges of the v3 `speed` / `pitchShift` hints, straight from the API reference.
# Used to validate the teacher-supplied values in schemas/lesson.py.
YANDEX_TTS_SPEED_MIN: float = 0.1
YANDEX_TTS_SPEED_MAX: float = 3.0
YANDEX_TTS_PITCH_MIN: int = -1000
YANDEX_TTS_PITCH_MAX: int = 1000
YANDEX_TTS_VOICES: frozenset[str] = frozenset(
    {
        "alena",
        "filipp",
        "ermil",
        "jane",
        "madirus",
        "omazh",
        "zahar",
        "dasha",
        "julia",
        "lera",
        "masha",
        "marina",
        "alexander",
        "kirill",
        "anton",
    }
)
# Empty tuple = voice takes no role hint (v3 rejects an unknown role with 400).
# Verified against the live API on 2026-08-12 — do not extend without testing.
YANDEX_TTS_ROLES_BY_VOICE: dict[str, tuple[str, ...]] = {
    "alena": ("neutral", "good"),
    "anton": ("good",),
    "zahar": ("neutral", "good"),
    "marina": ("neutral", "friendly", "whisper"),
    "filipp": (),
    "omazh": ("neutral",),
}
# Transient polza failures (429/5xx/timeout) are retried with exponential backoff;
# other 4xx (bad key, bad voice) fail fast. Mirrors LLM_MAX_RETRIES below.
POLZA_TTS_MAX_RETRIES: int = 3
# openai/tts-1 voice catalog accepted by polza (probed 2026-06-10: these 9 → 200,
# "ballad"/"verse" → 400). Single source of truth: the API voice validator
# (schemas/lesson.py) and the polza synth fallback both build on this. The
# frontend dropdown sends one of these names directly — no name translation.
POLZA_TTS_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
)
TTS_CACHE_TTL_DAYS: int = 7

# Chunk-level TTS disk cache (tts_service, keyed on _split_for_tts output). This
# is finer-grained than the whole-slide cache in tasks/video_pipeline.py: a
# single edited sentence in a long script only re-synthesizes its own chunk
# instead of invalidating the whole slide's cached audio.
TTS_CHUNK_CACHE_ENABLED: bool = True
TTS_CHUNK_CACHE_DIR_NAME: str = "tts_chunk_cache"

# Глубина раскрытия темы — единственный рычаг длительности урока.
# Длительность здесь СЛЕДСТВИЕ, а не вход: сколько можно рассказать, определяет
# сама презентация, преподаватель выбирает лишь подробность (docs/DECISIONS.md).
# Значения — бюджет слов на один СОДЕРЖАТЕЛЬНЫЙ слайд:
#   brief — тезисно; auto — совпадает с дефолтом системного промпта (150-300);
#   high  — потолок, за которым qwen-vl вместо текста уходит в цикл из
#           полноширинной CJK-пунктуации (проверено на бюджете 578 слов).
DETAIL_LEVEL_BODY_WORDS: dict[str, int] = {"brief": 120, "auto": 225, "high": 400}
DEFAULT_DETAIL_LEVEL: str = "auto"
WORDS_PER_MINUTE: int = 130  # spoken pace; mirrored in frontend useLessonDuration.ts
# Титульный и заключительный слайды несут меньше содержания, поэтому получают
# эту долю от бюджета содержательного слайда.
EDGE_SLIDE_BUDGET_WEIGHT: float = 0.4
# Доля буквенных символов, ниже которой ответ считается вырожденным и
# перезапрашивается (см. vision_analysis._looks_degenerate).
MIN_NARRATION_LETTER_RATIO: float = 0.5
# Ответы короче этого не проверяются на вырожденность — на нескольких словах
# доля букв слишком шумная.
DEGENERATE_CHECK_MIN_CHARS: int = 40

# Slide rendering
SLIDE_DPI: int = 150  # indistinguishable from 300 DPI on 1080p, 4× smaller PNGs

# LibreOffice ignores <a:bodyPr wrap="none"> and re-wraps text it had to render
# in a substituted font, without growing the spAutoFit box the extra line then
# overflows. Widening such boxes before conversion removes the reason to wrap.
# Deliberately a blunt multiplier: the substituted font is whatever fontconfig
# picks, so computing an exact text width would be guesswork either way.
NOWRAP_WIDEN_FACTOR: float = 2.0

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
ATTACHMENT_MAX_FILES: int = 10  # max files per submission (per kind)
ATTACHMENT_MAX_TOTAL_SIZE_MB: int = 1024  # max combined size of one submission
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
# Paid extension of that window, bought per submission by the teacher (see
# services/retention_service). Extensions accumulate: each one pushes the
# deadline this many days past the CURRENT effective deadline, not past `now`.
RETENTION_EXTENSION_DAYS: int = 90
# One reminder email is sent this many days before a submission's attachments
# are due for deletion (see purge_pipeline.notify_expiring_attachments).
RETENTION_REMINDER_DAYS_BEFORE: int = 7
# Extension pricing. Retention is a storage cost, so the price scales with the
# submission's actual bytes rather than being flat — see
# billing_service.estimate_retention_extension. Any non-empty submission costs
# at least BASE + 1, which is why CREDIT_WEIGHTS["retention_extend"] (2) stays a
# truthful shop-window figure for a typical small text submission.
RETENTION_EXTEND_BASE_CREDITS: int = 1
RETENTION_MB_PER_CREDIT: int = 100
# ── Lesson knowledge base (materials + notes) ────────────────────────────────
# Teacher-attached supplementary files. Same "store, never parse" contract as
# assignment attachments, but with NO retention window: a material lives as long
# as its lesson (deleted explicitly or by the hard purge of the lesson).
LESSON_MATERIAL_MAX_FILES: int = 30  # max materials per lesson
LESSON_MATERIAL_MAX_TOTAL_SIZE_MB: int = 2048  # max combined size per lesson
# Per-file ceiling by category (MB).
LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB: dict[str, int] = {
    "document": 100,
    "image": 50,
    "audio": 200,
    "video": 500,
    "archive": 200,
}
# Whitelist — MIME type → category. Source of truth for what may be attached to
# the knowledge base; the category drives the per-file size limit above.
LESSON_MATERIAL_ALLOWED_TYPES: dict[str, str] = {
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
# extension absent here is rejected outright.
LESSON_MATERIAL_EXTENSION_MIME: dict[str, str] = {
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
    "gif": "image/gif",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "zip": "application/zip",
}
# Hand-written markdown notes — length caps enforced by the Pydantic schema.
LESSON_NOTE_MAX_TITLE_CHARS: int = 255
LESSON_NOTE_MAX_CONTENT_CHARS: int = 50_000
LESSON_NOTE_MAX_PER_LESSON: int = 100
LESSON_MATERIAL_MAX_DESCRIPTION_CHARS: int = 2000

# Extension whitelist (lower-case, no dot) for the teacher-set per-assignment
# allowed_ext filter — separate from the system attachment whitelist above.
ASSIGNMENT_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "csv",
    "txt",
    "md",
    "rtf",
    "odt",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "zip",
)
ASSIGNMENT_DEFAULT_MAX_POINTS: float = 100.0
ASSIGNMENT_MAX_PROMPT_CHARS: int = 20000
ASSIGNMENT_MAX_TEXT_CHARS: int = 50000  # student answer body / teacher feedback
ASSIGNMENT_MAX_MESSAGE_CHARS: int = 4000  # one private-thread message

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
CACHE_GC_ENABLED: bool = True  # kill-switch for the cache GC pass only
SLIDES_CACHE_TTL_DAYS: int = 30  # slides_cache/<hash>/ dirs unused this long → evict
SLIDES_CACHE_MAX_BYTES: int = 5 * 1024**3  # 5 GiB cap (rendered PNGs are large)
SUMMARIES_CACHE_TTL_DAYS: int = 60  # .txt summaries: LLM-costly to redo → keep longer
SUMMARIES_CACHE_MAX_BYTES: int = 512 * 1024**2  # 512 MiB cap

# LessonVideo GC has its OWN kill-switch (separate from the caches): deleting a
# video version is IRREVERSIBLE, whereas a cache entry is reproducible — on an
# incident you want to disable video pruning without losing the disk-reclaim
# that may be the thing keeping storage from filling. NEVER deletes an
# is_published=True version, and always keeps the newest KEEP_UNPUBLISHED
# unpublished per lesson (a lesson is never left with zero videos).
LESSON_VIDEO_GC_ENABLED: bool = True  # kill-switch for the LessonVideo GC pass only
LESSON_VIDEO_UNPUBLISHED_TTL_DAYS: int = 30  # cold unpublished versions eligible after this
LESSON_VIDEO_KEEP_UNPUBLISHED: int = 2  # newest N unpublished per lesson always survive

# Startup reconciliation: lessons stuck in non-terminal status (analyzing /
# processing) for longer than this window are presumed to have lost their Celery
# task (Redis flushdb or crash without AOF) and are marked error on backend
# startup. Must exceed the worst-case pipeline runtime so that legitimately
# in-flight tasks during a rolling restart are not disturbed.
STUCK_LESSON_GRACE_MINUTES: int = 120

# ── Progress SSE (routers/lessons.progress_stream) ───────────────────────────
# Comment frame emitted this often so an idle stream keeps proxies and the
# browser from treating it as dead. Must stay well under nginx's
# proxy_read_timeout (300s in nginx/prod.conf.template).
SSE_HEARTBEAT_SECONDS: float = 15.0

# `retry:` hint sent once at the top of every stream — the delay the browser
# waits before reconnecting after the connection drops. Deliberately short: a
# blue-green switch cuts open streams when the old slot drains, and the client
# should be back on the new slot in seconds. Progress is republished from the
# Celery checkpoint on reconnect, so an early retry costs nothing.
SSE_RETRY_MS: int = 2000

# ── Worker-concurrency budget ────────────────────────────────────────────────
# Video/vision pool sizes are derived from the usable CPU count so a small host
# doesn't oversubscribe (thread contention, KNOWN_PROBLEMS §3.7) and a big host
# scales up. Each knob has an env-override in config.Settings (None → auto);
# an override is used VERBATIM (manual mode) and is NOT re-clamped.
#
# INVARIANT: TTS_WORKERS must equal the Silero container's NUMBER_OF_THREADS.
# Both docker-compose services read the SAME ${TTS_WORKERS} env var, so pinning
# it moves the pool and Silero together; not re-clamping the override is what
# keeps them exactly equal. Leave it unset only on ~4-core hosts, where the auto
# value (4) matches the compose fallback (see .env.example).
_CORE_CAP: int = 12  # ignore cores beyond this when scaling pools
_PEAK_MULT: int = 3  # guardrail asserted in tests: VIDEO_CONCURRENCY*(TTS+ENCODE)
# stays <= _PEAK_MULT * cores. >1 because TTS/vision threads
# mostly block on Silero/LLM IO, not local CPU.


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _derive_concurrency(cores: int) -> dict[str, int]:
    """Derive video/vision pool sizes from the usable CPU count.

    Floors keep the pipeline functional on tiny hosts (TTS>=2, ENCODE>=1,
    VIDEO>=1, VISION>=1); caps stop a many-core host from spawning hundreds of
    threads. At 4 cores this returns the historical 4/3/4 with 1 parallel lesson.
    """
    c = _clamp(cores, 1, _CORE_CAP)
    return {
        "TTS_WORKERS": _clamp(c, 2, 6),  # == Silero NUMBER_OF_THREADS
        "ENCODE_WORKERS": _clamp(c - 1, 1, 4),  # ffmpeg, CPU-bound
        "VISION_SUMMARY_CONCURRENCY": _clamp(c, 1, 6),  # IO-bound provider calls
        # parallel lessons — 2nd lesson only from 8 cores so peak threads stay
        # under _PEAK_MULT*cores at every core count (verified in the unit test).
        "VIDEO_CONCURRENCY": 1 if c <= 7 else (2 if c <= 11 else 3),
    }


# os.cpu_count() over-reports inside a cgroup-limited container, so CPU_BUDGET
# (env) caps it; None-safe fallback to 1 core.
_HOST_CORES: int = os.cpu_count() or 1
_USABLE_CORES: int = min(_HOST_CORES, settings.CPU_BUDGET) if settings.CPU_BUDGET else _HOST_CORES
_AUTO: dict[str, int] = _derive_concurrency(_USABLE_CORES)

# Env-override wins verbatim; None → derived value.
TTS_WORKERS: int = settings.TTS_WORKERS or _AUTO["TTS_WORKERS"]
ENCODE_WORKERS: int = settings.ENCODE_WORKERS or _AUTO["ENCODE_WORKERS"]
# Parallel video lessons per worker. The pipeline itself is one-lesson-per-task;
# this is the celery_video --concurrency, wired from the same env in compose.
VIDEO_CONCURRENCY: int = settings.VIDEO_CONCURRENCY or _AUTO["VIDEO_CONCURRENCY"]

# Segment encoding (still-image slide + narration audio). All segments must use
# identical params — concatenate_segments joins them with `-c copy` (no re-encode).
SEGMENT_FPS: int = 5  # slide is static; 25fps was pure waste
SEGMENT_AUDIO_BITRATE: str = "96k"  # mono narration doesn't need 192k
SEGMENT_AUDIO_CHANNELS: int = 1
SEGMENT_KEYFRAME_SECONDS: int = 2  # keyframe every ~2s keeps in-slide seeking smooth

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
# Parallel vision-summary calls (the alignment-hint pass) — bounded to stay under
# provider rate limits. Auto-derived from CPU; see the worker-concurrency budget
# above and its config.Settings override.
VISION_SUMMARY_CONCURRENCY: int = (
    settings.VISION_SUMMARY_CONCURRENCY or _AUTO["VISION_SUMMARY_CONCURRENCY"]
)

# Quiz
# default for new quizzes; per-quiz override in Quiz.pass_threshold
QUIZ_PASS_THRESHOLD: float = 0.6
QUIZ_NUM_OPTIONS: int = 4
QUIZ_MIN_QUESTIONS: int = 1
QUIZ_MAX_QUESTIONS: int = 20
# AI generation is requested per question type ("N single_choice, M true_false").
# 0 excludes a type entirely; the total across types stays within
# QUIZ_MIN_QUESTIONS..QUIZ_MAX_QUESTIONS. Both the request schema and the
# teacher UI read these bounds — don't restate them anywhere else.
QUIZ_MIN_QUESTIONS_PER_TYPE: int = 0
QUIZ_MAX_QUESTIONS_PER_TYPE: int = 10
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
# Free monthly allowance for that LLM grading, counted per TEACHER account and
# per graded open answer (usage_counters, period_key='YYYY-MM'). Deliberately
# NOT part of PLAN_CONFIGS: it is a technical floor identical on every plan, not
# a tariff lever. Answers beyond it are charged CREDIT_WEIGHTS['quiz_grade_overage']
# from the same balance video generation spends; with no credits left the answer
# silently falls back to manual review. See tasks/quiz_pipeline._authorize_grading.
AI_GRADING_FREE_ANSWERS_PER_MONTH: int = 100

# Billing / credits
# Per-operation credit cost for FLAT-priced operations. Video generation is
# priced by formula instead — see VIDEO_*_BASE_CREDITS below and
# billing_service.estimate_video_text/estimate_video_auto.
CREDIT_WEIGHTS: dict[str, int] = {
    "vision_analyze": 5,  # vision-анализ PPTX → SlideText (без видео)
    "slide_regen": 1,  # регенерация одного слайда через vision LLM
    "quiz_generate": 5,  # AI-генерация квиза (полная цена и при перегенерации)
    # AI-review вопросов квиза — teacher QA pass, always free (see quiz_teacher.ai_review).
    "ai_review": 0,
    "quiz_grade": 0,  # AI-проверка квиза в пределах месячной квоты — бесплатно
    # Один открытый ответ сверх AI_GRADING_FREE_ANSWERS_PER_MONTH.
    "quiz_grade_overage": 1,
    # Витринная цена продления хранения — типовая мелкая сдача. Фактическое
    # списание считает estimate_retention_extension от реального объёма файлов
    # (тот же приём, что quiz_grade: 0 — публичный прайс-лист vs реальный счёт).
    "retention_extend": 2,
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
# Измерено на ~22k слов сгенерированной озвучки: 6.96 символа на слово.
# Переводит бюджет слов целевой длительности в символы для тарификации TTS.
CHARS_PER_WORD: int = 7
# Vision-анализ тарифицируется по объёму текста, который он пишет: дека на 3
# слайда и лекция на 50 минут не могут стоить одинаково. База + посимвольная
# часть подобраны так, что дека без целевой длительности остаётся около
# прежней плоской пятёрки CREDIT_WEIGHTS['vision_analyze'].
VISION_ANALYZE_BASE_CREDITS: int = 2
VISION_CHARS_PER_CREDIT: int = 2000

# Provider cost rates (rubles) for the generation_usage margin journal.
TTS_RUB_PER_MCHAR: float = 1380.48
# SpeechKit is billed separately from the Polza rate above — verify against the
# AI Studio pricing page before trusting the margin journal.
YANDEX_TTS_RUB_PER_MCHAR: float = 1342.0  # SpeechKit API v1, с НДС
LLM_RUB_PER_MTOK_PROMPT: float = 17.49
LLM_RUB_PER_MTOK_COMPLETION: float = 63.5

# Lifetime trial for free accounts: usage_counters(period_key='lifetime').
# A trial lecture/quiz is consumed instead of credits while slots remain.
TRIAL_LECTURES: int = 2
TRIAL_QUIZZES: int = 2
TRIAL_MAX_SLIDES: int = 20  # cap per trial lecture
TRIAL_MAX_SCRIPT_CHARS: int = 15000  # cap per trial lecture (text mode)

# Tariff plans. Keys match CreditPlan enum values. Free accounts get no welcome
# credits — the lifetime trial (2 lectures + 2 quizzes) replaces them.
PLAN_CONFIGS: dict[str, dict[str, int]] = {
    "free": {"monthly_allowance": 0, "onetime_credits": 0, "price_rub": 0},
    "starter": {"monthly_allowance": 30, "onetime_credits": 0, "price_rub": 490},
    "pro": {"monthly_allowance": 120, "onetime_credits": 0, "price_rub": 1490},
    "school": {"monthly_allowance": 500, "onetime_credits": 0, "price_rub": 4990},
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
    "pack_50": {
        "title": "50 кредитов",
        "credits": 50,
        "price_rub": 190,
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
    },  # noqa: E501
    "pack_200": {
        "title": "200 кредитов",
        "credits": 200,
        "price_rub": 590,
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
    },  # noqa: E501
    "pack_500": {
        "title": "500 кредитов",
        "credits": 500,
        "price_rub": 1290,
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
    },  # noqa: E501
    "pack_1200": {
        "title": "1200 кредитов",
        "credits": 1200,
        "price_rub": 2690,
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
    },  # noqa: E501
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
RECONCILE_INTERVAL_MINUTES: int = 15  # beat cadence
RECONCILE_MIN_AGE_MINUTES: int = 10  # grace: let the task + poll settle first
RECONCILE_MAX_AGE_HOURS: int = 72  # stop re-querying long-dead payments
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
    "free": "free",
    "starter": "paid",
    "pro": "paid",
    "school": "paid",
}

# Celery scheduling priority per tier (passed to apply_async(priority=...)).
# IMPORTANT — Redis broker semantics: a LOWER number is HIGHER priority (0 is
# drained first, 9 last). This is the REVERSE of RabbitMQ. Verified against the
# Celery routing docs ("In Redis, priority 0 is considered the highest priority,
# while priority 9 is the lowest"). Hence enterprise=0 (highest), free=9 (lowest).
# Values must fall inside broker_transport_options["priority_steps"] in
# app/celery_app.py (currently 0..9).
TIER_PRIORITY: dict[str, int] = {
    "free": 9,
    "paid": 3,
    "enterprise": 0,
}

# Default per-type question counts offered by the generation dialog and used
# when the request omits type_counts. Key order is the order the UI renders the
# rows in; keys match the type strings used in generate_quiz_v2.
QUIZ_DEFAULT_TYPE_COUNTS: dict[str, int] = {
    "single_choice": 3,
    "multiple_choice": 1,
    "true_false": 1,
    "short_answer": 0,
}

# Email
# Lifetime of the signed email-verification token (itsdangerous max_age).
EMAIL_VERIFICATION_TTL_SECONDS: int = 60 * 60 * 24  # 24h
# Min seconds between two resend-verification requests for the same user
# (Redis cooldown, enforced on top of the slowapi per-IP limit).
EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS: int = 60
# send_email Celery task retry policy on retriable provider failures.
EMAIL_SEND_MAX_RETRIES: int = 3
EMAIL_SEND_RETRY_BACKOFF: int = 5  # base seconds; Celery grows it exponentially

# Notifications (product email subsystem — see services/notification_service.py).
# Auth mail (verification / password reset) does NOT go through it.
# Dedup window per (user, event, entity): a repeat inside it is dropped. Also what
# makes an acks_late replay of deliver_notification a no-op.
NOTIFY_DEDUP_TTL_SECONDS: int = 60 * 60 * 6  # 6h
# How often the beat job drains the per-user digest accumulators.
NOTIFY_DIGEST_INTERVAL_MINUTES: int = 30
# Cap on accumulated digest items; the overflow is collapsed into "и ещё N".
NOTIFY_DIGEST_MAX_ITEMS: int = 20
# Accumulator lifetime — a user whose flush never runs (Redis restart, beat down)
# doesn't keep a stale list forever. Generous multiple of the flush interval.
NOTIFY_DIGEST_TTL_SECONDS: int = 60 * 60 * 24
# Users drained per flush run; the rest wait for the next tick.
NOTIFY_DIGEST_FLUSH_BATCH: int = 500
# Presence entry lifetime in the SSE sorted set. Must exceed SSE_HEARTBEAT_SECONDS
# by a comfortable margin so a slow heartbeat doesn't read as "user left".
NOTIFY_PRESENCE_TTL_SECONDS: int = 45
# Lifetime of a one-click unsubscribe link. Long — the link must still work when
# the user digs the mail out of the archive weeks later.
NOTIFY_UNSUBSCRIBE_TTL_SECONDS: int = 60 * 60 * 24 * 365
# SPA route the unsubscribe endpoint redirects to.
NOTIFY_UNSUBSCRIBED_PATH: str = "/unsubscribed"

# Password reset
# Lifetime of a one-time password-reset token (DB-backed, only its hash is
# stored). Kept short — long enough to receive and click the email, no more.
PASSWORD_RESET_TTL_SECONDS: int = 60 * 30  # 30 min
# Entropy of the raw reset token (bytes handed to secrets.token_urlsafe).
PASSWORD_RESET_TOKEN_BYTES: int = 32
# SPA route that consumes the reset token; the raw token is appended as ?token=.
PASSWORD_RESET_PATH: str = "/reset-password"

# OAuth (social sign-in — see services/oauth_service.py)
# Lifetime of the Redis-held authorization state + PKCE verifier. Only has to
# survive one round trip through the provider's consent screen.
OAUTH_STATE_TTL_SECONDS: int = 60 * 10
# Lifetime of the pending-registration ticket handed to the SPA when a social
# identity has no local account yet (role + consents still missing).
OAUTH_PENDING_TICKET_TTL_SECONDS: int = 60 * 10
# Entropy (bytes handed to secrets.token_urlsafe) of the state, PKCE verifier
# and pending ticket. The verifier is larger — RFC 7636 wants 43-128 chars.
OAUTH_STATE_BYTES: int = 32
OAUTH_PKCE_VERIFIER_BYTES: int = 48
OAUTH_TICKET_BYTES: int = 32
# Per-request timeout for the two server-to-server provider calls (token
# exchange, userinfo). Short: the user is waiting on a blocked redirect.
OAUTH_HTTP_TIMEOUT_SECONDS: float = 10.0
# SPA route the callback bounces to when sign-in could not complete; the failure
# reason is appended as ?oauth=0&reason=...
OAUTH_FAILURE_PATH: str = "/login"
# SPA route that finishes registration for a brand-new social identity.
OAUTH_REGISTER_PATH: str = "/register"

# Registration consents (personal-data processing)
# Version of the legal documents the user is consenting to at registration time.
# Bump this whenever the privacy policy / terms change so we can tell which
# revision each user agreed to.
CONSENT_POLICY_VERSION: str = "2026-08-29"

# Access code generation
ACCESS_CODE_LENGTH: int = 6
# No I, O, 1, 0 — visually ambiguous characters excluded.
ACCESS_CODE_ALPHABET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCESS_CODE_MAX_RETRIES: int = 10
