# Third-party licenses & attributions

Edllm's own source code is MIT-licensed (see [LICENSE](LICENSE)). It stands on a
large stack of third-party libraries, models, and binaries that keep their **own**
licenses. This file is a best-effort inventory — the authoritative license for any
dependency is the one shipped inside that package. Versions below are pinned in
[`backend/requirements.txt`](backend/requirements.txt) and
[`frontend/package.json`](frontend/package.json).

**TL;DR for anyone deploying commercially:** the default TTS engine (Silero,
Russian voices) is **non-commercial only**. Read §1 before you charge money.

---

## 1. ⚠️ Requires attention — non-commercial / copyleft / license changes

| Component | License | What it means for you |
|---|---|---|
| **Silero TTS** — Russian models `v5_ru` / `v5_5_ru` (via the `navatusein/silero-tts-service` container, the default `TTS_PROVIDER=silero`) | **CC-BY-NC 4.0 — NON-COMMERCIAL** | **Free only for non-commercial use.** A commercial launch needs a **Silero Enterprise licence** (hello@silero.ai) *or* switching to a commercial provider: `TTS_PROVIDER=polza`, or Yandex SpeechKit. Only Silero's base `cis`/`en` TTS models are MIT — the Russian voices this project uses are not. |
| **FFmpeg** (video muxing/encoding, invoked as a binary) | **LGPL-2.1+**, or **GPL-2.0+** depending on how the binary was built (e.g. `--enable-gpl`) | Used as an external process, not linked into our code. Distribution obligations attach if **you redistribute the FFmpeg binary**; a pure SaaS that only *runs* it server-side generally does not trigger copyleft distribution terms. If you ship an image/appliance, honor LGPL/GPL. |
| **poppler / `pdftoppm`** (PDF→PNG) | **GPL-2.0 / GPL-3.0** | Same nuance as FFmpeg: called as a binary, no source-level linking. Copyleft obligations are about *redistributing the binary*, not about SaaS execution. |
| **LibreOffice (headless)** (PPTX→PDF) | **MPL-2.0** | File-level copyleft; invoked as an external binary. No obligations for normal server-side use. |
| **Redis** (broker + cache, used as a service) | **BSD-3-Clause** up to 7.2; **RSALv2 / SSPLv1** for 7.4+; **AGPLv3** re-added in 8.0 | We consume Redis over the network as an unmodified service — we neither embed nor resell it, so the source-available terms (which target offering Redis *itself* as a managed service) don't bite. Pin the version your policy allows. |
| **psycopg2-binary** `2.9.10` (Postgres driver) | **LGPL-3.0-only with exceptions** | Dynamically imported Python library; LGPL is satisfied by keeping it a replaceable dependency (which it is). |
| **odfpy** `1.4.1` (ODF text extraction) | **Dual: Apache-2.0 OR GPL-2.0** | You may use it under Apache-2.0 — permissive. |

---

## 2. Backend — permissive dependencies (MIT / BSD / Apache-2.0 / ISC / HPND)

Python packages from [`backend/requirements.txt`](backend/requirements.txt):

| Package | Version | License (typical) |
|---|---|---|
| fastapi | 0.136.1 | MIT |
| starlette (via fastapi) | — | BSD-3-Clause |
| uvicorn[standard] | 0.34.0 | BSD-3-Clause |
| gunicorn | 23.0.0 | MIT |
| sqlalchemy[asyncio] | 2.0.49 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| alembic | 1.18.4 | MIT |
| pydantic / pydantic-settings | 2.13.2 / 2.9.1 | MIT |
| PyJWT | 2.10.1 | MIT |
| argon2-cffi | 23.1.0 | MIT |
| python-multipart | 0.0.20 | Apache-2.0 |
| celery[redis] | 5.6.3 | BSD-3-Clause |
| redis (redis-py client) | 5.2.1 | MIT |
| openai (SDK) | 1.107.0 | Apache-2.0 |
| aiofiles | 25.1.0 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| Pillow | 11.2.1 | MIT-CMU (HPND) |
| numpy | 2.2.1 | BSD-3-Clause |
| scipy | 1.15.0 | BSD-3-Clause |
| python-pptx | 1.0.2 | MIT |
| pdf2image | — | MIT |
| pypdf | 5.1.0 | BSD-3-Clause |
| python-docx | 1.1.2 | MIT |
| striprtf | 0.0.28 | BSD-3-Clause |
| slowapi | 0.1.9 | MIT |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| jinja2 | 3.1.5 | BSD-3-Clause |
| cachetools | ≥5.0 | MIT |
| sentry-sdk[fastapi,celery,sqlalchemy] | ≥2.0 | MIT |
| structlog | ≥24.0 | MIT / Apache-2.0 (dual) |
| flower | ≥2.0 | BSD-3-Clause |
| prometheus-fastapi-instrumentator | ≥7.0 | ISC |
| prometheus-client | ≥0.20 | Apache-2.0 |
| boto3 | ≥1.34 | Apache-2.0 |
| sse-starlette | ≥1.6.1 | BSD-3-Clause |

*(psycopg2-binary and odfpy from this file are covered in §1.)*

---

## 3. Frontend — permissive dependencies (MIT / ISC / Apache-2.0)

JS packages from [`frontend/package.json`](frontend/package.json):

| Package | License |
|---|---|
| nuxt | MIT |
| vue / vue-router | MIT |
| pinia / @pinia/nuxt | MIT |
| lucide-vue-next | ISC |
| @nuxtjs/tailwindcss | MIT |
| tailwindcss | MIT |
| happy-dom | MIT |
| vitest | MIT |
| typescript | Apache-2.0 |

---

## 4. Runtime services & container images

| Image / service | Upstream license |
|---|---|
| `postgres` (PostgreSQL 17) | PostgreSQL License (permissive, BSD-like) |
| `redis` | see §1 |
| `navatusein/silero-tts-service` (wraps Silero models) | container MIT; **bundled Russian models CC-BY-NC 4.0 — see §1** |
| `nginx` | BSD-2-Clause |
| `grafana/grafana` | AGPLv3 (used unmodified as a service) |
| `prom/prometheus` | Apache-2.0 |
| `mher/flower` | BSD-3-Clause |

---

## 5. External providers (not bundled, used over the network)

- **Polza AI** — cloud LLM/vision/TTS gateway (OpenAI-compatible). Commercial API, its own ToS.
- **Ollama** — local LLM runtime (MIT); models pulled through it carry their own licenses (e.g. Qwen — Apache-2.0 / Tongyi Qianwen licenses depending on size).
- **Yandex Cloud** (YandexGPT / Vision / SpeechKit) — commercial API, its own ToS.
- **YooKassa** — payments provider, its own ToS.
- **Resend** — transactional email, its own ToS.

---

*If you spot an incorrect license here, please open an issue — the packages'
own `LICENSE` files are the source of truth, and we'll fix the table.*
