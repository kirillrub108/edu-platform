# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Edllm** — a teacher↔student SaaS LMS built around one signature feature: turn a PPTX + lecture script into a narrated MP4 lesson with an LLM/TTS pipeline, then deliver it to enrolled students. Around that core it also does AI-generated **quizzes**, **assignments** (file submissions + grading + private teacher↔student threads), per-lesson **comments**, a **gradebook**, **analytics**, student enrollment via **access codes**, and a **credit-based billing** layer (YooKassa). (The repo folder is still `edu-platform/` and the DB credentials remain `edu_user`/`edu_password`; only the product name and DB name `edllm` were rebranded.) Two halves of the codebase:

- `backend/` — FastAPI + Celery (Python 3.13). Routers are thin, services are fat (LLM, TTS, video, storage, vision, auth, billing, quiz, assignment, analytics, visibility). Long jobs (PPTX→MP4 pipeline, vision analysis, quiz generation, soft-delete purge, email) run in Celery.
- `frontend/` — Nuxt 3 in mostly-SPA mode (`/` is prerendered SSG, `/**` is `ssr: false`). Auto-imports, file-based routing. Separate teacher (`/dashboard`) and student (`/student/*`) cabinets.

Read `docs/ARCHITECTURE.md` first for the big picture, then `docs/DATA_FLOW.md` for end-to-end scenarios and `docs/AUTH_FLOW.md` for auth. `docs/KNOWN_PROBLEMS.md` is the canonical list of tech debt — check it before "fixing" something that looks weird. `docs/DEPLOYMENT.md` covers running the stack; `docs/DECISIONS.md` is the decision log.

## npm — запрещено

**Никогда не запускай `npm install`, `npm ci` или любые другие `npm` команды** — ни на хосте, ни внутри контейнера. Установка пакетов на Windows-хосте создаёт `node_modules` с Windows-бинарниками, которые ломают Linux-контейнер. Все зависимости управляются через Docker-образ.

## Commands

Everything is intended to run via Docker Compose. The `.env` at repo root is shared by all containers; `.env.example` is the template.

```bash
# Full stack: postgres, redis, silero-tts, backend, four Celery workers
# (celery_video, celery_vision, celery_quiz [runs beat], celery_email_worker),
# plus nginx (idle in dev on :8080), monitoring (prometheus, grafana :3001,
# flower :5555) and frontend.
docker-compose up --build

# Auto-apply migrations happens in backend lifespan (dev only — gated on
# RUN_MIGRATIONS_ON_STARTUP); to create a new one:
docker-compose exec backend alembic revision --autogenerate -m "describe change"
docker-compose exec backend alembic upgrade head     # usually unnecessary in dev, see "Migrations"

# Backend tests — run inside the backend image (testcontainers starts a sibling
# Postgres via the host Docker socket; details in backend/tests/README.md). Suite is
# split into tests/unit/ (pure-function / service tests) and tests/integration/
# (route tests using the conftest async client + factories).
docker-compose exec backend pytest -m "not slow"              # canonical full run
docker-compose exec backend pytest tests/unit                 # unit only
docker-compose exec backend pytest tests/integration          # routes only
docker-compose exec backend pytest tests/unit/test_tts_service.py::test_name   # single
docker-compose exec backend pytest                            # adds `slow` tier — needs real Ollama/Silero up

# Lint (ruff: rules E, F, I — line length 100, target py313)
docker-compose exec backend ruff check app

# Frontend tests (vitest + happy-dom, frontend/tests/) — run inside the frontend
# container, calling the binary directly (npm itself is banned, see above):
docker-compose exec frontend node_modules/.bin/vitest run

# Frontend dev server runs in its container on :3000. To run locally instead:
cd frontend && npm install && npm run dev

# Production (self-contained compose — NOT an override of the dev file):
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile migrate run --rm migrate
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

External dependency the containers cannot provide: a reachable **LLM + vision provider**. The default in `.env.example` is **Polza AI** (cloud, OpenAI-compatible) for both text and vision. The alternative is **Ollama on the host** with `qwen3` (text) and `qwen2.5vl:7b` (vision), reached via `host.docker.internal:11434` — pull those models if you point `LLM_BASE_URL`/`VISION_OLLAMA_BASE_URL` back to local Ollama. Either way, without a working provider, video generation fails at the LLM-split or vision-summary step. **Silero TTS** ships as a container; the cloud TTS alternative is Polza (`TTS_PROVIDER=polza`).

Open URLs:
- Frontend: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- Files served from local storage volume: http://localhost:8000/files/...
- Grafana: http://localhost:3001 · Flower (Celery): http://localhost:5555 · Prometheus: http://localhost:9090

## Architecture notes that aren't obvious from the file tree

### Async backend, sync Celery
`asyncpg` + `AsyncSession` everywhere in routers/services. Celery tasks use the sync URL (`DATABASE_URL.replace("+asyncpg", "+psycopg2")`) and a regular `Session`. Do not import `AsyncSession` into `app/tasks/*` — prefork workers will deadlock or hit greenlet errors. This split is intentional, see `docs/DECISIONS.md`.

### Four Celery workers, four queues (+ one beat)
`docker-compose.yml` runs a dedicated worker per queue: `celery_video` (queue=`video`, c=2), `celery_vision` (queue=`vision`, c=1), `celery_quiz` (queue=`quiz`, c=2), and `celery_email_worker` (queue=`celery_email`, c=2). Queues/routing are declared in `app/celery_app.py`; tasks live in `app/tasks/` (`video_pipeline`, `vision_pipeline`, `quiz_pipeline`, `purge_pipeline`, `email_pipeline`) and must be in its `include=[...]` list. When adding a new task, route it to the right queue or no worker will pick it up. **Beat** (the scheduler for the daily `purge_soft_deleted` job) is embedded in `celery_quiz` via `--beat` — exactly one beat must run cluster-wide, so don't add `--beat` to another worker or replicate that service.

**Tier-based priority:** jobs are scheduled with `apply_async(priority=...)` from `TIER_PRIORITY` (`constants.py`), tier derived from the user's `CreditPlan` via `PLAN_TIER_MAP`. On the **Redis** broker a *lower* number is *higher* priority (0 first, 9 last) — the reverse of RabbitMQ; `broker_transport_options` + `worker_prefetch_multiplier=1` make it actually take effect. Don't flip the ordering.

### Migrations apply on startup in dev, as a deploy step in prod
`app/main.py:_ensure_schema_at_head` runs `alembic upgrade head` inside the FastAPI lifespan **only when `RUN_MIGRATIONS_ON_STARTUP` is true** (the dev default) — forgetting to generate a migration after a model change then = backend refuses to start. In prod that flag is `false` and migrations run as the one-shot `migrate` service (`docker-compose.prod.yml`, `--profile migrate`) *before* the app rolls out. New models **must** be re-exported in `app/models/__init__.py` (along with any new enums — `LessonStatus`, `CreationMode`, `ContentType`, `AccessMode`, `UserRole`, `QuizStatus`, `AssignmentStatus`, etc. follow this pattern), otherwise Alembic autogenerate won't see them.

### Storage backend (local default, S3 optional) + static delivery
`STORAGE_BACKEND` (`config.py`) switches between `local` and `s3` (Yandex Object Storage / S3-compatible); `services/storage_service.py` abstracts both. In `local` mode everything (uploaded PPTX, generated PNG/WAV/MP4, caches, attachments) lives in `backend/storage/`, bind-mounted into the backend and every celery container, and served with HMAC-signed URLs (`services/signed_url_service.py`). **Who serves `/files/*` depends on `SERVE_STATIC_VIA_NGINX`:** dev (false) → FastAPI's `files.router`; prod (true) → nginx serves the bytes directly from the shared volume and FastAPI only mounts `files.internal_router` to verify the signature. The files router is registered **only when `STORAGE_BACKEND == "local"`**. Cache dirs `slides_cache/`, `summaries_cache/` and `tts_cache/` are keyed by content hash — deleting them is safe and just forces re-rendering, but they **grow unbounded** (no GC — see `docs/KNOWN_PROBLEMS.md`).

### Video pipeline concurrency
`app/tasks/video_pipeline.py` runs two thread pools in parallel (TTS pool + FFmpeg encoder pool) and chains them with `as_completed` so encoding slide *k* starts the moment its WAV is ready. If you touch this file, preserve the streaming relationship — going back to "TTS all → encode all" roughly doubles pipeline latency. Pool sizes and other tunables (`TTS_WORKERS`, `ENCODE_WORKERS`, `SILERO_MAX_CHARS`, `SLIDE_DPI`, `MAX_SCRIPT_BYTES`) live in `app/constants.py` — change them there, not inline.

### Slide rendering
PPTX → PNG is done inside `services/video_service.py` by shelling out to headless `libreoffice` (PPTX → PDF) then `pdftoppm`. There is no separate `slide_renderer` module anymore. Rendered PNGs are cached under `storage/slides_cache/<content-hash>/` and reused across re-runs.

### Middleware order in `main.py`
CORS is added **last** intentionally — `add_middleware` prepends, so the last-registered middleware is outermost. Final stack (outer→inner): `CORS → request_id → log_and_catch → Prometheus → routes`. CORS must be outside `log_and_catch` so a 500's JSON response still gets CORS headers; `request_id` binds the structlog contextvar before logging. The long comment in `main.py` explains why; do not "clean it up" by reordering. In production a wildcard `CORS_ORIGINS=["*"]` is a hard error (cookie auth needs an explicit allowlist) — see `_assert_cors_allowlist_safe`.

### Models with `onupdate=func.now()` need `__mapper_args__ = {"eager_defaults": True}`
Without it you get `MissingGreenlet` when serializing a row right after `UPDATE` (asyncpg refetches the server-generated value). Existing models already set this — copy the pattern for new ones.

### Frontend state
Pinia is the canonical state layer — auth lives in `src/stores/auth.ts` (`useAuthStore`); other stores: `student`, `studentCabinet`, `billing`, `comments`, `assignments`. `composables/useCreationMode.ts` is *not* a state singleton, just a module of constants (`CreationMode`, `CREATION_MODE_CARDS`). When adding new shared state, prefer a Pinia store over `useState('key', factory)` singletons.

### API client and auth (cookie-based — NOT Bearer/localStorage)
Auth runs on **httpOnly cookies + double-submit CSRF**, not `Authorization: Bearer`. No token ever touches JS/localStorage. `composables/useApi.ts` is the single fetch wrapper: it sends `credentials: 'include'` (the `access_token` cookie rides along), and for state-changing methods (`POST/PUT/PATCH/DELETE`, except `/auth/*`) it reads the non-httpOnly `csrf_token` cookie and forwards it as the `X-CSRF-Token` header — the server (`dependencies.py:get_current_token_payload`) 403s if they don't match. Refresh is **reactive**: on a 401 it calls `/auth/refresh` (refresh token is in an httpOnly cookie scoped to `/api/v1/auth/refresh`) behind a **singleflight `refreshPromise`** so a burst of 401s triggers one rotation, then retries the original request once. On refresh failure it calls `store.clearSession()` and redirects to `/login`. `/auth/me` is treated as a session probe (a 401 there means "anonymous", no redirect). Don't add a second refresh path or reintroduce Bearer/localStorage — extend `useApi`. Server side: Argon2id passwords, refresh-token rotation with Redis families + reuse detection (`services/auth_service.py`); full picture in `docs/AUTH_FLOW.md`.

### AI-operation gating (CI-enforced)
Every endpoint that triggers an LLM / vision / TTS call **must** sit behind `require_verified_email` or `require_verified_teacher` (email-verified users only) **and** be listed in `AI_GATED_ENDPOINTS` in `dependencies.py`. The guard test `tests/integration/test_ai_gating_guard.py` fails if you add such a route without doing both. Student quiz grading is intentionally excluded (it's marketed as free — see `docs/DECISIONS.md`). Video/vision/quiz generation also reserves credits up front (`RESERVE`) and releases/charges on completion — see "Billing" below.

### Direct video upload (no-AI lessons)
`POST /api/v1/lessons/{id}/upload-video` (`routers/lessons.py`) attaches a ready-made MP4/WebM/MOV/MKV to a lesson and publishes it immediately — no pipeline, no credits, `CreationMode.video_upload`. Validation = extension + content-type + 16-byte magic sniff, size capped by `MAX_VIDEO_UPLOAD_BYTES` (2 GB, `constants.py`). It deliberately sits behind plain `require_teacher` (lesson create too) — only AI-triggering endpoints need a verified email, so don't "tighten" these to `require_verified_teacher`. Frontend entry: the `video_upload` card in `CREATION_MODE_CARDS` + `components/LessonVideoUploadSection.vue`.

### Course cover image
`POST /api/v1/courses/{id}/cover` (`routers/courses.py`, plain `require_teacher`) stores an uploaded image (`.jpg/.jpeg/.png/.webp/.gif`, ≤ 5 MB) under `storage/covers/` and sets `course.cover_image_path`. `CourseOut` carries **two** cover fields: `cover_url` (a teacher-set link, re-signed per request) and `cover_image_url` — the course serializer prefers the uploaded `cover_image_path`, else falls back to the re-signed `cover_url`. Don't conflate them.

### Billing, credits & quotas
Spend is governed by **credits**, not request quotas. `services/billing_service.py` is the source of truth: AI ops `RESERVE` credits up front then charge/release on completion; flat costs live in `CREDIT_WEIGHTS` and video is priced by formula (`VIDEO_*_BASE_CREDITS`, `TTS_CHARS_PER_CREDIT`, `estimate_video_text/auto`). Free accounts get a **lifetime trial** (`TRIAL_LECTURES`/`TRIAL_QUIZZES`, tracked in `usage_counters` with `period_key='lifetime'`) instead of welcome credits. Plans (`PLAN_CONFIGS`) grant a monthly allowance with `CREDIT_CARRYOVER_RATIO`; one-time top-ups come from `CREDIT_PACKAGES`. Payments go through **YooKassa** (`services/yookassa_service.py`, `routers/billing.py`): the webhook re-fetches the payment from YooKassa's API and never trusts the notification body. Admin grant/renewal endpoints (`/billing/admin/*`) are gated by a shared secret in the `X-Admin-Token` header (`require_admin`), not a UserRole; an empty `ADMIN_API_TOKEN` disables them. The `generation_usage` journal records provider ₽ cost for margin tracking and feeds the Prometheus cost collector.

### Quizzes, grading & assignments
**Quizzes** (`routers/quiz_teacher.py` / `quiz_student.py`, `services/quiz_service.py`, `tasks/quiz_pipeline.py`): teachers AI-generate or hand-author questions (`single_choice`/`multiple_choice`/`true_false`/`short_answer`); generation runs on the `quiz` queue and is credit-charged. Student open-answer grading is **free LLM grading** (`services/grading_service.py`) with anti-abuse caps (`GRADING_MAX_ANSWER_CHARS`, `GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY`). **Assignments** (`routers/assignment_teacher.py` / `assignment_student.py`, `services/assignment_service.py`): teacher-set text tasks, student file submissions, grades, and a private per-submission message thread. Attachments are only *stored*, never parsed server-side (avoids XXE/zip-bomb); the MIME/extension whitelist and size/count caps live in `constants.py` (`ATTACHMENT_*`). Submission files auto-purge `ATTACHMENT_RETENTION_DAYS_AFTER_GRADED` days after grading via `purge_pipeline`. Grades roll up in `services/gradebook_service.py` (`routers/gradebook.py`); per-class/per-lesson quiz metrics (attempts, avg score, pass rate, per-student results with teacher override) live in `services/analytics_service.py` (`routers/analytics.py`).

### Publish / visibility chain
`services/visibility_service.py` is the single source of truth for student visibility. **For an already-enrolled student the access rule is `module.is_published AND lesson.is_published` — `course.is_published` is intentionally NOT part of it.** Course publication gates only *discovery / new enrollment* (catalog, preview, enroll): unpublishing a course hides it from the catalog and blocks new sign-ups while **preserving access for everyone already enrolled**; unpublishing a *module or lesson* is the lever that hides content from all students. Teachers/owners bypass this and see drafts. Unpublishing a parent does **not** clear the children's flags; hiding is purely a read-time effect of this AND. Drafts are hidden with **404, not 403**, so the API never reveals that an unpublished resource exists (see `dependencies.require_lesson_access`). Don't re-derive the rule inline — call `module_visible_to_student` / `lesson_visible_to_student`. Rationale and the per-flag publish endpoints are logged in `docs/DECISIONS.md` §34.

### Observability
**Sentry** is initialized in both `main.py` (FastAPI) and `celery_app.py` (Celery), disabled when `SENTRY_DSN` is empty; `before_send` drops sub-500 HTTPExceptions so 4xx don't spam issues. **Prometheus**: `prometheus-fastapi-instrumentator` exposes `/metrics` (gated on `METRICS_ENABLED`), plus a DB-backed `UsageCostCollector` (`services/usage_service.py`) — DB-backed because AI runs in Celery workers whose in-process counters are never scraped. Celery task metrics are wired via signals in `celery_app.py`. Logs are structured JSON (`structlog`, `logging_config.py`) with a per-request `request_id`. Grafana (`:3001`) and Flower (`:5555`) round it out.

### Email (transactional)
Verification + notification email is sent **only** from the `send_email` Celery task on the `celery_email` queue (`tasks/email_pipeline.py`). Provider is pluggable; **Resend** is implemented. Verification tokens are signed with `itsdangerous` (`services/email_token_service.py`, `EMAIL_VERIFICATION_TTL_SECONDS`). Leaving `RESEND_API_KEY` empty in dev is fine — the task retries and fails with no other side effects.

### Rate limiting
`slowapi` is wired in `app/limiter.py` and registered on `app.state.limiter` in `main.py`, with a dedicated 429 handler. Per-route limits use the `@limiter.limit(...)` decorator (see `routers/auth.py`). Tests that hit limited endpoints in a loop will start 429-ing — use distinct client IPs or reset the limiter in fixtures.

### Routing rules (frontend)
- `middleware/auth.ts` — **opt-in per page** (`definePageMeta({ middleware: 'auth' })`), not a global guard. Keep it that way — public pages (landing/login/register) must stay reachable.
- `middleware/guest.ts` — bounces already-authenticated users off `/login`, `/register`
- `middleware/teacher.ts` — bounces students out of teacher pages to `/student/dashboard`
- Route role: teachers land on `/dashboard`, students on `/student/dashboard`

## Conventions

- **Routers** stay tiny: parse → authorize via `dependencies.py` (`require_teacher`, `require_student`, `require_verified_*`, `get_current_user`, `require_lesson_access`, `get_owned_lesson`) → 1–3 calls into `services/` or the DB → return. Business logic belongs in `services/`. New routers must be `include_router`-ed in `main.py`.
- **Pydantic v2** schemas under `app/schemas/`, one file per resource. DTO names follow `XCreate` / `XUpdate` / `XRead`.
- **Argon2** is the active password hasher (`argon2-cffi` in requirements). Some older docs still mention bcrypt — the code uses Argon2.
- **`task_id` is persisted in the DB** (`analyze_task_id`, `video_task_id` on `Lesson`) so the frontend can resume polling after a page refresh. When adding new long-running tasks, follow the same pattern instead of returning the id only in the HTTP response.
- **Tunables go in `app/constants.py`** — TTS/encode pool sizes, quiz/billing/assignment/email limits, plan & package configs, tier priorities. Don't hard-code them inline.
- **No new top-level docs.** If you need to capture a decision, append to `docs/DECISIONS.md` (or `KNOWN_PROBLEMS.md` for tech debt) rather than creating a new file.

## Provider swaps

LLM/vision provider is set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`; `VISION_*`) — Polza AI (cloud default), Ollama, and YandexGPT all speak the OpenAI protocol, so `services/llm_service.py` / `services/vision_analysis.py` don't need changes; switching provider is an env edit. TTS is selected by `TTS_PROVIDER` (`silero` container default, or `polza` cloud) inside `services/tts_service.py` — both keep the same `synthesize()` signature so the pipeline doesn't change.

## Production deployment

`docker-compose.prod.yml` is **self-contained — NOT an override** of the dev compose. Never run `-f docker-compose.yml -f docker-compose.prod.yml`: Compose merges lists, so dev bind-mounts would silently leak in. Code comes only from the built images. It adds over dev: **gunicorn** (uvicorn workers, no `--reload`) for the backend, `frontend/Dockerfile.prod` (`nuxt build` → node server), a one-shot **`migrate`** service (`--profile migrate`, run before `up`), a **`db_backup`** sidecar (periodic `pg_dump -Fc` → `db_backups` volume, retention `BACKUP_RETENTION_DAYS`), **nginx** with `nginx/prod.conf` serving `/files/*` directly + TLS, and a **certbot** profile (`deploy/init-letsencrypt.sh` + the systemd renew timer in `deploy/systemd/`). Storage is the shared `app_storage` named volume instead of a host bind-mount. Restore a backup with `... run --rm db_backup sh -c 'pg_restore -c -d "$PGDATABASE" /backups/<file>.dump'`. See `docs/DEPLOYMENT.md` §7.
