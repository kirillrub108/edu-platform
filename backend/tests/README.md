# Backend tests

## Running (canonical — inside the backend container)

The stack is already brought up via `docker compose up`. Run the suite
inside the running backend container:

```powershell
# Full suite (127 tests, ~12 s, zero skips) — uses LibreOffice / poppler /
# ffmpeg baked into the backend image and spins up a sibling Postgres via
# testcontainers + host Docker socket.
docker compose exec backend pytest -m "not slow"

# Unit tests only (no DB, no sibling container)
docker compose exec backend pytest tests/unit -m unit

# Coverage report (excludes the two task pipelines by default — see
# pyproject.toml [tool.coverage.run])
docker compose exec backend pytest -m "not slow" --cov=app --cov-report=term-missing

# Including the `slow` tier (real Ollama / Silero — needs those services up)
docker compose exec backend pytest
```

This works because `docker-compose.yml` for the `backend` service:

* installs `requirements-dev.txt` in the image (see `backend/Dockerfile`);
* mounts `/var/run/docker.sock` so `testcontainers` can ask the **host**
  Docker daemon to start a sibling `postgres:17-alpine` container for the
  test session — i.e. Docker-outside-of-Docker, not DinD;
* sets `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal` and
  `TESTCONTAINERS_RYUK_DISABLED=true` so the test process inside the
  container can reach the sibling Postgres on the host network, and
  doesn't wait for the unreachable Ryuk reaper;
* bind-mounts `./backend/tests` and `./backend/pyproject.toml` into
  `/app/` so editing tests on the host shows up immediately — no rebuild
  needed unless you change `requirements*.txt` or system packages.

## Running on the host (Windows / macOS / Linux dev box)

This still works if you have Python + Docker available on the host. You
lose access to the `test_slide_renderer` test (it needs `pdftoppm` —
auto-skipped when the binary isn't on PATH):

```powershell
cd backend
pip install -r requirements-dev.txt
pytest -m "not slow"
```

## Markers

| Marker | Meaning | Run in CI? |
| --- | --- | --- |
| `unit` | Pure functions, no DB or network | yes |
| `integration` | Requires the PG testcontainer (and patched external services) | yes |
| `slow` | Real Ollama / Silero (the rest of the stack is baked into the backend image, no separate skip needed) | no (default-skipped) |

`pytest -m "not slow"` is the default CI command.

## Adding a new test

* **Unit** — drop a file in `tests/unit/test_<thing>.py`. Mark with
  `pytestmark = pytest.mark.unit`. No `db_session`, no HTTP.
* **Integration HTTP** — drop in `tests/integration/test_<area>_routes.py`.
  Use the `client` fixture (`httpx.AsyncClient` over `ASGITransport`) and
  the `db_session` fixture for direct DB checks. Tokens come from the
  `teacher_token` / `student_token` fixtures.
* **Celery pipeline** — see `test_pipeline_logic.py`. Use the `sync_session`
  fixture (NOT `db_session`) — the Celery worker holds its own psycopg2
  connection and cannot see writes made through the async SAVEPOINT
  fixture.

## Mocking a new external service

The convention is **module-attribute monkey-patching**:

```python
from app.services import some_service as mod

def test_thing(monkeypatch):
    monkeypatch.setattr(mod.some_service, "external_call", lambda *_a, **_k: "fake")
```

For HTTP-based services (TTS, vision, LLM), patch the underlying
client/transport at the `tts_service.httpx.get`, `llm_service.client`, or
`vision_analysis_service._ollama_client` attribute level.

For subprocess-based code (LibreOffice / pdftoppm / FFmpeg), use the
provided `mock_subprocess` fixture — it replaces `subprocess.run` inside
`app.services.video_service` and synthesises the expected output files.

## Caveats

* **Two databases at once.** Integration HTTP tests run inside a
  SAVEPOINT and roll back at teardown. Celery pipeline tests run against
  the real PG via the sync engine. Mixing them in the same test file is
  possible but error-prone; keep them apart.
* **Rate limiting.** Disabled via an `autouse` fixture in `conftest.py`.
  If you want to test rate-limit behaviour, re-enable in your test
  explicitly: `app.state.limiter.enabled = True`.
* **Lifespan is bypassed.** Tests do not run the FastAPI lifespan
  handler, so the alembic-upgrade-on-startup path is not exercised here.
  Migrations are applied once via the `_alembic_upgraded` fixture
  instead. The lifespan code is run live every time `docker-compose up`
  brings the backend up.
