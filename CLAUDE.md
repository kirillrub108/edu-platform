# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Edllm** — SaaS that turns a PPTX + lecture script into a narrated video lesson, then exposes it to students. (The repo folder is still `edu-platform/` and the DB credentials remain `edu_user`/`edu_password`; only the product name and DB name `edllm` were rebranded.) Two halves of the codebase:

- `backend/` — FastAPI + Celery (Python 3.13). Routers are thin, services are fat (LLM, TTS, video, storage, vision, auth). Long jobs (PPTX→MP4 pipeline, vision analysis) run in Celery.
- `frontend/` — Nuxt 3 in mostly-SPA mode (`/` is prerendered SSG, `/**` is `ssr: false`). Auto-imports, file-based routing.

Read `docs/ARCHITECTURE.md` first for the big picture, then `docs/DATA_FLOW.md` for end-to-end scenarios. `docs/KNOWN_PROBLEMS.md` is the canonical list of tech debt — check it before "fixing" something that looks weird.

## npm — запрещено

**Никогда не запускай `npm install`, `npm ci` или любые другие `npm` команды** — ни на хосте, ни внутри контейнера. Установка пакетов на Windows-хосте создаёт `node_modules` с Windows-бинарниками, которые ломают Linux-контейнер. Все зависимости управляются через Docker-образ.

## Commands

Everything is intended to run via Docker Compose. The `.env` at repo root is shared by all containers; `.env.example` is the template.

```bash
# Full stack: postgres, redis, silero-tts, backend, four Celery workers
# (celery_video, celery_vision, celery_quiz [runs beat], celery_email_worker),
# plus monitoring (prometheus, grafana :3001, flower :5555) and frontend.
docker-compose up --build

# Auto-apply migrations happens in backend lifespan; to create a new one:
docker-compose exec backend alembic revision --autogenerate -m "describe change"
docker-compose exec backend alembic upgrade head     # usually unnecessary, see "Migrations" below

# Backend tests — run inside the backend image (testcontainers starts a sibling
# Postgres via the host Docker socket; details in backend/tests/README.md). Suite is
# split into tests/unit/ (pure-function / service tests) and tests/integration/
# (route tests using the conftest async client + factories).
docker-compose exec backend pytest -m "not slow"              # canonical full run
docker-compose exec backend pytest tests/unit                 # unit only
docker-compose exec backend pytest tests/integration          # routes only
docker-compose exec backend pytest tests/unit/test_tts_service.py::test_name   # single
docker-compose exec backend pytest                            # adds `slow` tier — needs real Ollama/Silero up

# Frontend tests (vitest + happy-dom, frontend/tests/) — run inside the frontend
# container, calling the binary directly (npm itself is banned, see above):
docker-compose exec frontend node_modules/.bin/vitest run

# Frontend dev server runs in its container on :3000. To run locally instead:
cd frontend && npm install && npm run dev
```

External dependency the containers cannot provide: **Ollama on the host** with `qwen3:8b` (text) and `qwen2.5vl:7b` (vision). The backend reaches it via `host.docker.internal:11434`. Without these models pulled, video generation will fail at the LLM-split or vision-summary step.

Open URLs:
- Frontend: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- Files served from local storage volume: http://localhost:8000/files/...

## Architecture notes that aren't obvious from the file tree

### Async backend, sync Celery
`asyncpg` + `AsyncSession` everywhere in routers/services. Celery tasks use the sync URL (`DATABASE_URL.replace("+asyncpg", "+psycopg2")`) and a regular `Session`. Do not import `AsyncSession` into `app/tasks/*` — prefork workers will deadlock or hit greenlet errors. This split is intentional, see `docs/DECISIONS.md`.

### Four Celery workers, four queues (+ one beat)
`docker-compose.yml` runs a dedicated worker per queue: `celery_video` (queue=`video`, c=2), `celery_vision` (queue=`vision`, c=1), `celery_quiz` (queue=`quiz`, c=2), and `celery_email_worker` (queue=`celery_email`, c=2). Queues/routing are declared in `app/celery_app.py`. When adding a new task, route it to the right queue or no worker will pick it up. **Beat** (the scheduler for the daily `purge_soft_deleted` job) is embedded in `celery_quiz` via `--beat` — exactly one beat must run cluster-wide, so don't add `--beat` to another worker.

### Migrations auto-apply on backend start
`app/main.py:_ensure_schema_at_head` runs `alembic upgrade head` inside the FastAPI lifespan. Forgetting to generate a migration after a model change = backend refuses to start. New models **must** be re-exported in `app/models/__init__.py` (along with any new enums — `LessonStatus`, `CreationMode`, `ContentType`, `AccessMode`, `UserRole` follow this pattern), otherwise Alembic autogenerate won't see them.

### Storage backend (local default, S3 optional)
`STORAGE_BACKEND` (`config.py`) switches between `local` and `s3` (Yandex Object Storage / S3-compatible); `services/storage_service.py` abstracts both. In `local` mode everything (uploaded PPTX, generated PNG/WAV/MP4, caches) lives in `backend/storage/`, bind-mounted into the backend and every celery container, and served read-only via the `files` router at `/files/*` with HMAC-signed URLs (`services/signed_url_service.py`); that router is **registered only when `STORAGE_BACKEND == "local"`**. Cache dirs `slides_cache/` and `summaries_cache/` are keyed by content hash — deleting them is safe and just forces re-rendering.

### Video pipeline concurrency
`app/tasks/video_pipeline.py` runs two thread pools in parallel (TTS pool + FFmpeg encoder pool) and chains them with `as_completed` so encoding slide *k* starts the moment its WAV is ready. If you touch this file, preserve the streaming relationship — going back to "TTS all → encode all" roughly doubles pipeline latency. Pool sizes and other tunables (`TTS_WORKERS`, `ENCODE_WORKERS`, `SILERO_MAX_CHARS`, `SLIDE_DPI`, `MAX_SCRIPT_BYTES`) live in `app/constants.py` — change them there, not inline.

### Slide rendering
PPTX → PNG is done inside `services/video_service.py` by shelling out to headless `libreoffice` (PPTX → PDF) then `pdftoppm`. There is no separate `slide_renderer` module anymore. Rendered PNGs are cached under `storage/slides_cache/<content-hash>/` and reused across re-runs.

### Middleware order in `main.py`
CORS is added **last** intentionally — `add_middleware` prepends, so the last-registered middleware is outermost. The long comment in `main.py` explains why; do not "clean it up" by reordering.

### Models with `onupdate=func.now()` need `__mapper_args__ = {"eager_defaults": True}`
Without it you get `MissingGreenlet` when serializing a row right after `UPDATE` (asyncpg refetches the server-generated value). Existing models already set this — copy the pattern for new ones.

### Frontend state
Pinia is the canonical state layer — auth lives in `src/stores/auth.ts` (`useAuthStore`). `composables/useCreationMode.ts` is *not* a state singleton, just a module of constants (`CreationMode`, `CREATION_MODE_CARDS`). When adding new shared state, prefer a Pinia store over `useState('key', factory)` singletons.

### API client and auth (cookie-based — NOT Bearer/localStorage)
Auth runs on **httpOnly cookies + double-submit CSRF**, not `Authorization: Bearer`. No token ever touches JS/localStorage. `composables/useApi.ts` is the single fetch wrapper: it sends `credentials: 'include'` (the `access_token` cookie rides along), and for state-changing methods (`POST/PUT/PATCH/DELETE`, except `/auth/*`) it reads the non-httpOnly `csrf_token` cookie and forwards it as the `X-CSRF-Token` header — the server (`dependencies.py:get_current_token_payload`) 403s if they don't match. Refresh is **reactive**: on a 401 it calls `/auth/refresh` (refresh token is in an httpOnly cookie scoped to `/api/v1/auth/refresh`) behind a **singleflight `refreshPromise`** so a burst of 401s triggers one rotation, then retries the original request once. On refresh failure it calls `store.clearSession()` and redirects to `/login`. `/auth/me` is treated as a session probe (a 401 there means "anonymous", no redirect). Don't add a second refresh path or reintroduce Bearer/localStorage — extend `useApi`. Server side: Argon2id passwords, refresh-token rotation with Redis families + reuse detection (`services/auth_service.py`); full picture in `docs/AUTH_FLOW.md`.

### AI-operation gating (CI-enforced)
Every endpoint that triggers an LLM / vision / TTS call **must** sit behind `require_verified_email` or `require_verified_teacher` (email-verified users only) **and** be listed in `AI_GATED_ENDPOINTS` in `dependencies.py`. The guard test `tests/integration/test_ai_gating_guard.py` fails if you add such a route without doing both. Video/vision generation also reserves credits up front (`RESERVE`) and releases/charges on completion — see `services/billing_service.py` and `CREDIT_WEIGHTS` in `constants.py`.

### Direct video upload (no-AI lessons)
`POST /api/v1/lessons/{id}/upload-video` (`routers/lessons.py`) attaches a ready-made MP4/WebM/MOV/MKV to a lesson and publishes it immediately — no pipeline, no credits, `CreationMode.video_upload`. Validation = extension + content-type + 16-byte magic sniff, size capped by `MAX_VIDEO_UPLOAD_BYTES` (2 GB, `constants.py`). It deliberately sits behind plain `require_teacher` (lesson create too) — only AI-triggering endpoints need a verified email, so don't "tighten" these to `require_verified_teacher`. Frontend entry: the `video_upload` card in `CREATION_MODE_CARDS` + `components/LessonVideoUploadSection.vue`.

### Rate limiting
`slowapi` is wired in `app/limiter.py` and registered on `app.state.limiter` in `main.py`, with a dedicated 429 handler. Per-route limits use the `@limiter.limit(...)` decorator (see `routers/auth.py`). Tests that hit limited endpoints in a loop will start 429-ing — use distinct client IPs or reset the limiter in fixtures.

### Routing rules
- `middleware/auth.ts` — **opt-in per page** (`definePageMeta({ middleware: 'auth' })`), not a global guard. Keep it that way — public pages (landing/login/register) must stay reachable.
- `middleware/guest.ts` — bounces already-authenticated users off `/login`, `/register`
- `middleware/teacher.ts` — bounces students out of teacher pages to `/student/dashboard`
- Route role: teachers land on `/dashboard`, students on `/student/dashboard`

## Conventions

- **Routers** stay tiny: parse → authorize via `dependencies.py` (`require_teacher`, `require_student`, `get_current_user`) → 1–3 calls into `services/` or the DB → return. Business logic belongs in `services/`.
- **Pydantic v2** schemas under `app/schemas/`, one file per resource. DTO names follow `XCreate` / `XUpdate` / `XRead`.
- **Argon2** is the active password hasher (`argon2-cffi` in requirements). Some older docs still mention bcrypt — the code uses Argon2.
- **`task_id` is persisted in the DB** (`analyze_task_id`, `video_task_id` on `Lesson`) so the frontend can resume polling after a page refresh. When adding new long-running tasks, follow the same pattern instead of returning the id only in the HTTP response.
- **No new top-level docs.** If you need to capture a decision, append to `docs/DECISIONS.md` (or `KNOWN_PROBLEMS.md` for tech debt) rather than creating a new file.

## Provider swaps

LLM provider is set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) — both Ollama and YandexGPT speak the OpenAI protocol, so `services/llm_service.py` doesn't need changes. TTS provider is hard-coded to Silero today; swapping to Yandex SpeechKit means rewriting the body of `services/tts_service.py:synthesize()` while keeping its signature, so the pipeline doesn't change.
