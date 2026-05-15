# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

SaaS that turns a PPTX + lecture script into a narrated video lesson, then exposes it to students. Two halves of the codebase:

- `backend/` — FastAPI + Celery (Python 3.13). Routers are thin, services are fat (LLM, TTS, video, storage, vision, auth). Long jobs (PPTX→MP4 pipeline, vision analysis) run in Celery.
- `frontend/` — Nuxt 3 in mostly-SPA mode (`/` is prerendered SSG, `/**` is `ssr: false`). Auto-imports, file-based routing.

Read `docs/ARCHITECTURE.md` first for the big picture, then `docs/DATA_FLOW.md` for end-to-end scenarios. `docs/KNOWN_PROBLEMS.md` is the canonical list of tech debt — check it before "fixing" something that looks weird.

## Commands

Everything is intended to run via Docker Compose. The `.env` at repo root is shared by all containers; `.env.example` is the template.

```bash
# Full stack (postgres, redis, silero-tts, backend, celery_video, celery_vision, frontend)
docker-compose up --build

# Auto-apply migrations happens in backend lifespan; to create a new one:
docker-compose exec backend alembic revision --autogenerate -m "describe change"
docker-compose exec backend alembic upgrade head     # usually unnecessary, see "Migrations" below

# Backend tests (pytest is in requirements? — run inside the backend image):
docker-compose exec backend pytest                    # all
docker-compose exec backend pytest tests/test_slide_renderer.py::test_name   # single

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

### Two Celery workers, two queues
`docker-compose.yml` runs `celery_video` (queue=`video`, concurrency=2) and `celery_vision` (queue=`vision`, concurrency=1) separately. When adding a new task, route it to the right queue or the worker won't pick it up. (Note: `docs/ARCHITECTURE.md` §8.3 still describes the old single-worker setup — the code is the source of truth.)

### Migrations auto-apply on backend start
`app/main.py:_ensure_schema_at_head` runs `alembic upgrade head` inside the FastAPI lifespan. Forgetting to generate a migration after a model change = backend refuses to start. New models **must** be re-exported in `app/models/__init__.py`, otherwise Alembic autogenerate won't see them.

### Local storage, not S3
Everything (uploaded PPTX, generated PNG/WAV/MP4, caches) is in `backend/storage/`, bind-mounted into the backend and both celery containers. Exposed read-only via FastAPI `StaticFiles` at `/files/*` (URLs are signed — see `services/signed_url_service.py`). Cache directories `slides_cache/` and `summaries_cache/` are keyed by content hash; deleting them is safe and just forces re-rendering.

### Video pipeline concurrency
`app/tasks/video_pipeline.py` runs two thread pools in parallel (TTS pool + FFmpeg encoder pool) and chains them with `as_completed` so encoding slide *k* starts the moment its WAV is ready. If you touch this file, preserve the streaming relationship — going back to "TTS all → encode all" roughly doubles pipeline latency.

### Middleware order in `main.py`
CORS is added **last** intentionally — `add_middleware` prepends, so the last-registered middleware is outermost. The long comment in `main.py` explains why; do not "clean it up" by reordering.

### Models with `onupdate=func.now()` need `__mapper_args__ = {"eager_defaults": True}`
Without it you get `MissingGreenlet` when serializing a row right after `UPDATE` (asyncpg refetches the server-generated value). Existing models already set this — copy the pattern for new ones.

### Frontend state
Pinia is installed (`@pinia/nuxt` in `nuxt.config.ts` `modules`), and there's a `src/stores/` directory. There are also legacy `useState('key', factory)` singletons in some composables (`useAuth`, `useCreationMode`). When extending, follow the convention already used by the page you're editing — don't mix paradigms in the same feature.

### API client and auth
`composables/useApi.ts` is the single fetch wrapper: adds `Authorization: Bearer …` from `localStorage`, and on 401 clears tokens and redirects to `/login` (refresh-token flow is *not* wired — see `KNOWN_PROBLEMS.md` §1.2 before adding it).

### Routing rules
- `middleware/auth.ts` — global guard for authenticated routes
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
