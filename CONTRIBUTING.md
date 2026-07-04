# Contributing to Edllm

Thanks for taking a look. This is a Docker-first project — the whole stack
(FastAPI, Celery ×4, Postgres, Redis, Silero, Nuxt, monitoring) runs from one
`docker-compose`. Please keep your workflow inside the containers.

## 🚫 The one hard rule: no `npm`

**Never run `npm install`, `npm ci`, or any `npm` command — not on the host, not
in the container.** On a Windows host it produces a `node_modules/` full of
Windows binaries that break the Linux frontend container. All JS dependencies are
managed through the Docker image. To run frontend tooling, call the binary
directly inside the container:

```bash
docker-compose exec frontend node_modules/.bin/vitest run
```

If you must add a JS dependency: edit `frontend/package.json`, rebuild the image,
and delete the container's `node_modules/.platform` marker to force a re-seed —
do **not** install on the host.

## Getting the stack up

```bash
cp .env.example .env          # then fill/tweak values — see .env.example comments
docker-compose up --build
```

- Frontend: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

An external **LLM + vision provider** is the one thing the containers can't ship.
The default `.env.example` points at **Polza AI** (cloud, OpenAI-compatible). To
run fully local, point `LLM_BASE_URL` / `VISION_OLLAMA_BASE_URL` at
`host.docker.internal:11434/v1` and `ollama pull qwen3` + `qwen2.5vl:7b`. Without a
working provider, video generation fails at the LLM-split / vision step.

## Tests, lint, migrations (all via `docker-compose exec`)

```bash
# Backend tests (testcontainers spins up a sibling Postgres via the host socket)
docker-compose exec backend pytest -m "not slow"     # canonical full run
docker-compose exec backend pytest tests/unit          # unit only
docker-compose exec backend pytest tests/integration   # routes only

# Lint (ruff: E, F, I — line length 100, target py313)
docker-compose exec backend ruff check app

# Frontend tests
docker-compose exec frontend node_modules/.bin/vitest run

# New migration after a model change (autogenerate)
docker-compose exec backend alembic revision --autogenerate -m "describe change"
```

In dev, migrations auto-apply on backend startup (`RUN_MIGRATIONS_ON_STARTUP`
is true), so after a model change you usually just generate the revision and
restart. If the backend refuses to start, you probably forgot to generate one.

## Common tasks

**Add an HTTP route.** Routers stay thin: parse → authorize via `dependencies.py`
(`require_teacher`, `require_student`, `require_verified_*`, `get_current_user`,
`require_lesson_access`) → 1–3 calls into `services/` → return. Business logic
lives in `services/`, never in the router.
1. Create `backend/app/routers/<name>.py` with `router = APIRouter(prefix=..., tags=[...])`.
2. `app.include_router(<name>.router)` in `backend/app/main.py`.
3. If it triggers an LLM/vision/TTS call, it **must** be behind
   `require_verified_email`/`require_verified_teacher` **and** listed in
   `AI_GATED_ENDPOINTS` in `dependencies.py` — a CI guard test enforces both.

**Add a DB model.**
1. Create it under `backend/app/models/`, following the existing patterns
   (models with `onupdate=func.now()` need `__mapper_args__ = {"eager_defaults": True}`).
2. **Re-export it (and any new enum) in `backend/app/models/__init__.py`** —
   otherwise Alembic autogenerate won't see it.
3. Generate a migration (command above).

**Add a Celery task.** Async backend, **sync** Celery — do not import
`AsyncSession` into `app/tasks/*` (prefork workers deadlock). Tasks use the
sync engine.
1. Add the task under `backend/app/tasks/<pipeline>.py`.
2. Add its module to the `include=[...]` list in `backend/app/celery_app.py`.
3. Route it to the right queue (`video` / `vision` / `quiz` / `celery_email`) —
   an unrouted task no worker will ever pick up.
4. Persist any long-running `task_id` on the DB row (like `video_task_id`) so the
   frontend can resume polling after a refresh.

**Tunables** (pool sizes, quiz/billing/email/attachment limits, plan configs) go
in `backend/app/constants.py` — don't hard-code them inline.

## Conventions

- Pydantic v2 schemas under `app/schemas/`, one file per resource; DTO names
  `XCreate` / `XUpdate` / `XRead`.
- Argon2id is the password hasher (not bcrypt, despite some older docs).
- **No new top-level docs.** Capture decisions in `docs/DECISIONS.md`, tech debt
  in `docs/KNOWN_PROBLEMS.md` — don't create new doc files.
- Keep changes surgical: touch only what the change requires; match surrounding
  style. Add a test that reproduces a bug before fixing it.

## Pull requests

- Branch off `master`, keep the PR focused.
- Make sure `ruff check app` and `pytest -m "not slow"` pass in the container.
- Describe *what* and *why*; link the relevant `docs/` section if you changed
  behavior.

> The absence of this file (and `SECURITY.md`) used to be tracked as item 4.6 in
> `docs/KNOWN_PROBLEMS.md` — if that entry is still open, it can now be closed.
