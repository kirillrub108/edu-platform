# ARCHITECTURE — общая картина системы

> Документ для junior-разработчика, который только пришёл в проект. Цель — за 30 минут чтения сформировать рабочую ментальную модель: что из чего состоит, кто с кем разговаривает, и почему было выбрано именно это.

---

## 1. Что это за продукт (одна фраза)

**Edllm** — SaaS, который из загруженной PPTX-презентации и (опционально) текста доклада автоматически собирает видеолекцию с озвучкой и публикует её студентам.

---

## 2. Стек технологий и почему именно он

### Backend — Python 3.13

| Технология | Зачем |
|---|---|
| **FastAPI 0.136** | async из коробки, авто-генерируется OpenAPI/Swagger, у Pydantic-валидации лучший DX в Python-мире. Альтернативы (Django REST, Flask) либо синхронны, либо требуют ручной работы со schema. |
| **SQLAlchemy 2.0 (async)** | мейнстрим Python ORM с поддержкой async. Нужен ORM, потому что в схеме есть много связей с каскадными удалениями (User → Courses → Modules → Lessons → SlideTexts). Сырыми SQL это поддерживать неудобно. |
| **asyncpg + psycopg2** | dual-driver. asyncpg — быстрый async-драйвер для FastAPI. psycopg2 нужен Celery worker'у, потому что он работает в синхронных prefork-процессах. |
| **PostgreSQL 17** | JSONB (для опций квизов), uuid, timestamp with timezone, enum. Все эти типы используются. SQLite не подошёл бы — нет JSONB и серверного `func.now()`. |
| **Alembic** | миграции схемы. Запускаются автоматически в `lifespan` при старте FastAPI (см. `app/main.py:_ensure_schema_at_head`). |
| **Celery 5.6 + Redis 7** | долгие фоновые задачи. Генерация видео занимает 1-5 минут — нельзя держать HTTP-запрос открытым всё это время. Celery даёт стандартный паттерн «положил в очередь → воркер обработал → клиент опросил статус». |
| **Pydantic v2** | валидация request/response. Автоматически интегрируется с FastAPI и генерирует OpenAPI-схемы. |
| **PyJWT (HS256) + Argon2id** | аутентификация на httpOnly-куках + double-submit CSRF, ротация refresh-семейств в Redis. Пароли — Argon2id (`argon2-cffi`). См. [AUTH_FLOW.md](AUTH_FLOW.md). |
| **slowapi** | per-route rate limiting (`limiter.py`); 429-handler в `main.py`. |
| **Resend + itsdangerous** | транзакционные письма (верификация, «видео готово») через провайдер Resend; подписанные stateless-токены верификации. |
| **Sentry + Prometheus + structlog** | наблюдаемость: трейсы/ошибки (Sentry), метрики (`prometheus-fastapi-instrumentator` + Celery-сигналы), структурные JSON-логи с `request_id`. |
| **OpenAI SDK** | универсальный клиент к LLM. Polza AI (облачный дефолт), Ollama и YandexGPT говорят на OpenAI-протоколе → один и тот же код для всех провайдеров; выбор — правкой env. |
| **TTS: Polza / Yandex SpeechKit v3 / Silero** | `TTS_PROVIDER` выбирает бэкенд (`tts_service.py`). Прод по умолчанию — **Yandex SpeechKit v3** (`.env.prod.example`, дешевле v1, поддержка амплуа/скорости/питча). Самостоятельный **Silero** — бесплатный только для НЕкоммерческого использования (русские модели `v5_ru`/`v5_5_ru` — CC-BY-NC 4.0, см. [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md)); раньше запускался отдельным docker-контейнером (`navatusein/silero-tts-service`) в compose, с 2026-08-12 контейнер убран из `docker-compose.yml`/`docker-compose.prod.yml` — self-host теперь ручной. См. [DECISIONS.md §15](DECISIONS.md#15-silero-tts-отдельным-контейнером). |
| **LibreOffice headless** | единственный надёжный способ конвертировать PPTX в PDF без потери шрифтов и эмодзи. Альтернатив на Python нет. |
| **FFmpeg + poppler (pdftoppm)** | индустриальный стандарт для рендеринга PDF в PNG и склейки кадров с аудио в MP4. |

### Frontend — Node 22 / TypeScript

| Технология | Зачем |
|---|---|
| **Nuxt 3.14 (SPA)** | Vue + готовый file-based routing + auto-imports + composables. SSR отключён (`ssr: false`) — приложение работает как чистая SPA, что упрощает деплой (статика). |
| **Vue 3.5** | реактивность, простой шаблонный синтаксис. |
| **Tailwind CSS 3.4** | utility-first CSS — UI пишется быстро без отдельных `.css` файлов. |
| **lucide-vue-next** | современная библиотека SVG-иконок. |

| **Pinia 3** | канонический слой состояния. Сторы: `auth`, `billing`, `comments`, `assignments`, `student`, `studentCabinet`, `courseEditor`, `preview` (`frontend/src/stores/`). |

**State теперь на Pinia, а не на `useState`.** Раньше глобальное состояние держали в `useState('key', factory)` — сейчас канонический слой это **Pinia** (`useAuthStore` и др.). `composables/useCreationMode.ts` — это *не* стор, а модуль констант. Новое shared-состояние добавляем стором, а не `useState`-синглтоном.

### Инфраструктура

- **docker-compose** (dev) с ~12 сервисами (см. секцию 4); отдельный self-contained **`docker-compose.prod.yml`** для прода (gunicorn, nginx+TLS, one-shot `migrate`, сайдкар `db_backup`, certbot) — см. [DEPLOYMENT.md](DEPLOYMENT.md) §7.
- Внешняя зависимость — **LLM+vision провайдер**. По умолчанию (`.env.example`) это **Polza AI** (облако, OpenAI-совместимый) и для текста, и для vision. Альтернативы — **Ollama на хосте** (`qwen3` + `qwen2.5vl:7b`) через `host.docker.internal:11434`, или **Yandex AI Studio** (`ai.api.cloud.yandex.net`, тоже OpenAI-совместимый эндпоинт — тот же код-путь, что и Ollama/Polza; см. [DECISIONS.md](DECISIONS.md) §45). Переключение — правка env, кода не трогает (см. §14, [DECISIONS.md](DECISIONS.md)).
- Локальное файловое хранилище в `backend/storage/` (volume). `/files/*` отдаётся **кастомным `files`-роутером с HMAC-подписанными URL** (`signed_url_service.py`), а не голым `StaticFiles`; в проде (`SERVE_STATIC_VIA_NGINX=true`) байты отдаёт nginx, FastAPI лишь верифицирует подпись. Альтернатива хранилища — S3 (`STORAGE_BACKEND=s3`).

---

## 3. Основные модули и связи

```
┌─────────────────────────────────────────────────────────────────┐
│                       Browser (студент или teacher)              │
│                       Nuxt SPA — :3000                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP + JSON · httpOnly-cookie + CSRF
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend — :8000                       │
│   middleware:  CORS → request_id → log_and_catch → Prometheus   │
│   routers:     auth · courses · lessons · slides · uploads ·    │
│                students · quiz_teacher · quiz_student · comments │
│                · gradebook · analytics · billing · files ·      │
│                assignment_teacher · assignment_student          │
│   services:    auth · llm · tts · storage · video · vision ·    │
│                quiz · grading · gradebook · comment · billing · │
│                email · email_token · signed_url · analytics ·   │
│                assignment · visibility · file_validation        │
│   tasks (Celery): video · vision · quiz · email · purge ·        │
│                   payment (settle/reconcile) · disk-GC           │
└──────┬──────────────────────────────────┬───────────────────────┘
       │                                  │
       ▼                                  ▼
┌─────────────┐                   ┌──────────────┐
│ PostgreSQL  │                   │    Redis     │ — broker + result
│ users       │                   │ celery queue │   backend + auth-state
│ courses     │                   │ + auth/csrf  │   (refresh-семейства,
│ modules     │                   └──────┬───────┘    blacklist, cooldown)
│ lessons     │                          │
│ slide_texts │       ┌────────────────────────────────────────┐
│ enroll/quiz │       │  Celery workers (prefork, по очередям): │
│ credits     │       │   video (c=2)  → video_pipeline         │
│ comments    │       │   vision (c=1) → vision_pipeline        │
│ …           │       │   quiz (c=2,+beat) → quiz / purge       │
└─────────────┘       │   email (c=2)  → email_pipeline         │
       ▲              │  Внешние вызовы:                        │
       │              │   • LibreOffice (PPTX→PDF)              │
       └──────────────┤   • pdftoppm    (PDF→PNG)               │
       sync engine    │   • LLM (split+SSML): Polza/Yandex/Ollama│
       (psycopg2)     │   • Vision (narration): то же, OpenAI-совм│
                      │   • TTS: Polza / Yandex SpeechKit v3 /   │
                      │     self-host Silero HTTP :9898          │
                      │   • FFmpeg (image+wav → MP4)            │
                      └────────┬────────────────────────────────┘
                               │
                               ▼
                       ┌──────────────────────────┐
                       │  Local storage:          │
                       │  /app/storage/           │
                       │   ├── pptx/              │
                       │   ├── videos/            │
                       │   ├── lessons/<id>/...   │
                       │   ├── slides_cache/      │
                       │   └── summaries_cache/   │
                       │  Раздаётся через         │
                       │  FastAPI /files/*        │
                       └──────────────────────────┘
```

---

## 4. Сервисы (как они подняты в docker-compose)

| Контейнер | Образ | Порт | Зачем |
|---|---|---|---|
| `postgres` | postgres:17-alpine | 5432 | основная БД |
| `redis` | redis:8-alpine | 6379 | брокер Celery + result backend + auth-state (с паролем) |
| `backend` | (build ./backend) | 8000 | FastAPI с uvicorn `--reload` |
| `celery_video` | образ backend | — | queue `video`, `-c 2` — PPTX→MP4 пайплайн |
| `celery_vision` | образ backend | — | queue `vision`, `-c 1` — vision-LLM анализ слайдов |
| `celery_quiz` | образ backend | — | queue `quiz`, `-c 2`, **`--beat`** — генерация/проверка тестов, расчёт платежей + 4 периодические задачи (см. ниже) |
| `celery_email_worker` | образ backend | — | queue `celery_email`, `-c 2` — транзакционные письма |
| `nginx` | nginx:1.27-alpine | 8080 | в dev простаивает (FastAPI сам отдаёт `/files/*`); в проде отдаёт `/files/*` + TLS-термирование |
| `prometheus` | prom/prometheus | 9090 | сбор метрик с backend |
| `grafana` | grafana/grafana | 3001 | дашборды поверх Prometheus |
| `flower` | образ backend | 5555 | мониторинг Celery (basic-auth) |
| `frontend` | (build ./frontend) | 3000 | Nuxt dev server (`nuxt dev --host 0.0.0.0`) |

> **Прод (`docker-compose.prod.yml`, self-contained):** backend через `gunicorn` (uvicorn-воркеры, без `--reload`), фронт через `Dockerfile.prod` (`nuxt build` → node-сервер), one-shot сервис `migrate` (`alembic upgrade head` до роллаута), сайдкар `db_backup` (периодический `pg_dump -Fc`), nginx с TLS + `certbot`, и деплой на push в `master` автоматизирован через GitHub Actions + SSH (`deploy/deploy.sh`: sha-теги, conditional dump, авто-rollback). Подробности и порядок деплоя — [DEPLOYMENT.md](DEPLOYMENT.md) §7.
>
> **`silero-tts` больше не сервис compose** (убран 2026-08-12 — некоммерческая лицензия
> русских моделей Silero). `TTS_PROVIDER=silero` в коде и в `.env.example` остаётся дефолтом,
> но требует теперь ручного self-host; из коробки работают `TTS_PROVIDER=polza`/`yandex`. См.
> [DECISIONS.md §15](DECISIONS.md#15-silero-tts-отдельным-контейнером) и [DEPLOYMENT.md](DEPLOYMENT.md) §5 «TTS».

Все в общей сети `edu-network` — общаются по DNS-именам контейнеров (`backend → postgres:5432` и т.д.).

> **Важно про очереди:** каждый воркер слушает свою очередь (`--queues=…`). Новая Celery-задача
> попадёт к воркеру, только если её зароутить в правильную очередь — иначе её никто не возьмёт.
> **Beat-планировщик** встроен ровно в один воркер (`celery_quiz --beat`); в кластере он должен быть
> единственным. Beat гоняет **четыре** периодические задачи (все в очередь `quiz`, см.
> [celery_app.py](../backend/app/celery_app.py) `beat_schedule`):
> `purge_soft_deleted` (ежедневно 03:00), `reconcile_pending_payments` (каждые
> `RECONCILE_INTERVAL_MINUTES`=15 мин, бэкстоп зависших платежей ЮKassa),
> `gc_disk_caches` (04:00, TTL+size-cap eviction для `slides_cache`/`summaries_cache`) и
> `gc_lesson_videos` (04:30, прунинг холодных НЕопубликованных версий `LessonVideo`).
> См. [DECISIONS.md](DECISIONS.md) и [docker-compose.yml](../docker-compose.yml).

---

## 5. Основные модули backend в деталях

```
backend/app/
├── main.py            ← точка входа (FastAPI app, middleware, lifespan,
│                        startup-reconciliation зависших уроков)
├── config.py          ← pydantic-settings, читает .env (SECRET_KEY обязателен,
│                        prod-guard на слабый ключ)
├── constants.py       ← ВСЕ тюнинг-параметры (пулы, лимиты, тарифы, TTL)
├── database.py        ← async engine, get_db, Base, глобальный soft-delete фильтр
├── dependencies.py    ← get_current_user, require_teacher/_student/_verified_*,
│                        CSRF, AI_GATED_ENDPOINTS, require_lesson_access
├── celery_app.py      ← инстанс Celery (broker=Redis), очереди, beat, приоритеты
├── limiter.py         ← slowapi rate limiting
├── logging_config.py  ← structlog (JSON-логи, request_id)
├── redis_client.py    ← Redis-клиент (auth-state, чекпоинты)
├── models/            ← SQLAlchemy ORM (один файл = одна доменная сущность)
├── schemas/           ← Pydantic DTO (вход/выход API)
├── routers/           ← HTTP endpoints, по одному файлу на ресурс
├── services/          ← переиспользуемая бизнес-логика
└── tasks/             ← Celery-задачи (video/vision/quiz/email/purge/payment)
```

**Важная архитектурная конвенция:**
- `routers/` — *тонкие*: парсят запрос, проверяют права, делают 1-3 вызова в `services/` или БД, возвращают ответ.
- `services/` — *толстые*: вся реальная бизнес-логика (LLM-промпты, FFmpeg-команды, генерация JWT) живёт здесь.
- `models/` — *чистые*: только описание схемы, без поведения.

Это «light controllers, fat services» — стандартный паттерн, который держит роутеры читаемыми.

---

## 6. Основные модули frontend в деталях

```
frontend/src/
├── app.vue                  ← <NuxtLayout><NuxtPage/></NuxtLayout> + brand-токены
├── layouts/
│   ├── default.vue          ← AppHeader + контейнер
│   ├── bare.vue             ← без header (лендинг, dashboard)
│   ├── workspace.vue        ← teacher-кабинет (страница урока и т.п.)
│   ├── student-cabinet.vue  ← студенческий кабинет (сайдбар, /student/*)
│   └── student.vue          ← старый студенческий layout (легаси, не сливать)
├── stores/                  ← Pinia (канонический state)
│   ├── auth.ts              ← useAuthStore: user/isAuthenticated/login/logout
│   ├── billing.ts · comments.ts · assignments.ts
│   ├── student.ts · studentCabinet.ts
│   └── courseEditor.ts · preview.ts   ← редактор курса, «глазами студента»
├── middleware/
│   ├── auth.ts              ← opt-in на странице: редирект на /login (не глобальный)
│   ├── guest.ts             ← уводит залогиненных с /login,/register
│   ├── teacher.ts           ← студентов отправляет в /student/dashboard
│   └── student.ts           ← преподавателей уводит из /student/*
├── composables/
│   ├── useApi.ts            ← API-клиент: cookie-auth (credentials:include),
│   │                          double-submit CSRF, реактивный refresh на 401
│   ├── useProgressStream.ts ← SSE-подписка на прогресс Celery-задачи
│   ├── useAiGuard.ts        ← открывает «подтвердите email» на AI-действиях
│   ├── useCreationMode.ts   ← режимы создания урока (модуль констант, не стор)
│   ├── useVideoGeneration / useVisionAnalysis / useLessonData
│   ├── useQuizAttempt / useQuizAuthoring / useQuizPreview
│   └── useBillingMeta / useMetrika / useLanding* / useScroll*
├── plugins/                 ← metrika.client.ts (Яндекс.Метрика), scroll-*
├── pages/                   ← file-based routing (дети всегда в foo/index.vue!)
│   ├── index.vue            ← лендинг
│   ├── login.vue / register.vue / forgot-password.vue / reset-password.vue
│   ├── verify-email.vue / account.vue / billing.vue / join.vue
│   ├── dashboard.vue        ← teacher: список курсов
│   ├── courses/
│   │   ├── create.vue / index.vue
│   │   └── [id]/            ← index.vue (модули+уроки+публикация), gradebook.vue,
│   │       └── preview/     ← курс «глазами студента» (+ preview урока)
│   ├── lessons/[id]/        ← index.vue ★ главная рабочая страница (~820 строк),
│   │                          quiz-results.vue
│   ├── analytics/           ← quiz-results.vue (+ [lessonId].vue)
│   ├── legal/               ← offer, privacy, refund, contacts, pdn-consent
│   └── student/             ← dashboard, courses/[id], courses/[courseId]/lessons/
│                              [lessonId], assignments, quizzes, results
└── components/
    ├── SlideTextEditor.vue  ★ редактор текстов слайдов
    ├── lesson/              ← PptxUploader, ScriptPanel, VideoGenerationPanel,
    │                          VisionPanel, WorkflowNav, LessonHeader
    ├── quiz/QuestionForm · QuizEditor · QuizTaker · AttemptListPanel
    ├── assignments/         ← Editor, Review, Submit, Thread, панели teacher/student
    ├── student/             ← LessonView (плеер+квиз+задания), StudentSidebar
    ├── Landing*             ← секции лендинга
    ├── PipelineStages.vue   ← stepper прогресса
    ├── CreationModeChooser / CourseCard / CourseCoverUpload / StatusBadge
    ├── CreditBalanceWidget / GenerationCostModal / VerifyEmailModal
    ├── AppHeader / AppSidebar / AppLogo / LessonPlayer
    └── UiButton / UiInput / UiTabs
```

> ⚠️ Правило роутинга: страница с детьми — всегда каталог с `index.vue`
> (`pages/lessons/[id]/index.vue`), а не `pages/lessons/[id].vue` рядом с каталогом —
> иначе Nuxt рендерит детей в несуществующий `<NuxtPage>` (пустой экран).

---

## 7. Data flow одной строкой

> Browser (Vue) → `/api/v1/*` → FastAPI router → Pydantic-валидация → service / async SQLAlchemy → PostgreSQL · если задача долгая, в `Celery.delay()` → Redis → нужный Celery-воркер → внешние сервисы (LLM/TTS/FFmpeg) → результат в storage + БД → фронт получает прогресс по **SSE** (`/lessons/{id}/progress-stream`) с поллингом `/task-status/{id}` как fallback.

> ⚠️ **Обновление:** прогресс долгих задач теперь стримится через **SSE** (`sse-starlette` +
> `EventSource`), а не только поллится. См. `routers/lessons.py:progress_stream` и
> `composables/useProgressStream.ts`. Это делает решение «polling вместо SSE» в [DECISIONS.md](DECISIONS.md) §26 устаревшим.

Подробные пошаговые сценарии — в [DATA_FLOW.md](DATA_FLOW.md).

---

## 8. Главные архитектурные решения и trade-offs

> Подробное обоснование каждого — в [DECISIONS.md](DECISIONS.md). Здесь — сжатый список.

### 8.1 Async FastAPI + sync Celery worker
- **Решение:** в web-стороне всё async (`asyncpg`, `AsyncSession`); в Celery — синхронно (`psycopg2`, обычный `Session`).
- **Почему:** Celery с `prefork`-пулом сам не async. Каждая задача — отдельный процесс. Делать async внутри prefork-процесса нет смысла — overhead есть, выгоды нет.
- **Trade-off:** в воркере используется `_sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")`. Две точки настройки connection pool. Если попробуешь `await db.commit()` через `AsyncSession` в Celery-задаче — словишь runtime errors.

### 8.2 Локальное файловое хранилище по умолчанию, S3 — опция
- **Решение (обновлено):** дефолт — `backend/storage/` volume (`STORAGE_BACKEND=local`);
  S3-бекенд (Yandex Object Storage / совместимый) **уже реализован** в
  `storage_service.py` и включается `STORAGE_BACKEND=s3` (+ `S3_*`-переменные).
- **Почему:** MVP-скорость; интерфейс абстрагирован с самого начала.
- **Trade-off:** local-режим не масштабируется на горизонталь (несколько backend-инстансов
  не увидят файлов друг друга) и без бэкапа volume контент теряется; переезд на S3 — операционный
  шаг (перенос уже существующих файлов), код готов.

### 8.3 Несколько Celery-воркеров по очередям
- **Решение (обновлено):** раньше был один воркер на всё. Сейчас — **отдельный воркер на очередь**:
  `video` (c=2), `vision` (c=1), `quiz` (c=2, +beat), `celery_email` (c=2).
- **Почему:** изолирует ресурсы — медленный GPU-bound vision-анализ больше не конкурирует за слоты
  с CPU-bound encoding'ом, а транзакционные письма не ждут за пайплайном.
- **Trade-off:** больше контейнеров и `--queues`-маршрутизации; новую задачу надо явно зароутить в
  нужную очередь, иначе её никто не возьмёт. Beat встроен в один воркер (`celery_quiz`) — он должен
  быть единственным в кластере.

### 8.4 Vision LLM (Ollama qwen2.5vl:7b) вместо OCR
- **Решение:** для генерации текста по слайдам используется vision-модель, а не tesseract/paddleocr.
- **Почему:** LLM понимает контекст и пишет связное повествование, а не извлекает символы. Качество готового видео без vision-LLM — нечитаемое.
- **Trade-off:** тяжёлая зависимость на хост (Ollama + 7-14B модели), 30-60 секунд на слайд, нестабильное качество, требует ручного запуска `ollama pull` перед стартом.

### 8.5 LibreOffice headless для PPTX→PDF
- **Решение:** единственный способ корректно отрендерить PPTX (с шрифтами, эмодзи, картинками) в PDF.
- **Почему:** Python-библиотеки (`python-pptx`) умеют только парсить XML, но не рендерить.
- **Trade-off:** Docker-образ +500MB, медленный старт LibreOffice (~5 сек), отдельный `lo-emoji-substitution.xcu` для замены эмодзи-шрифтов.

### 8.6 Каскад рендеринга PPTX → PDF → PNG
- **Решение:** `LibreOffice (PPTX→PDF) → pdftoppm (PDF→PNG, 150 DPI)`.
- **Почему:** `pdftoppm` (poppler) даёт качественный антиалиасинг и быстрый рендеринг. Прямого рендеринга PPTX→PNG в LibreOffice headless нет.
- **Кеш:** хеш-функция `md5(pptx_bytes) + DPI` → если PPTX уже обрабатывался, кеш в `storage/slides_cache/<hash>/` минует обе стадии (~30 секунд экономии).

### 8.7 Двойной thread-pool в задаче генерации видео
- **Решение:** в `tasks/video_pipeline.py` параллельно работают `tts_pool` (4 потока, по запросу к TTS-провайдеру — Polza/Yandex SpeechKit/self-host Silero) и `enc_pool` (3 потока, по FFmpeg-процессу). Цепочка: как только TTS слайда K готов, тут же стартует encoding K, не дожидаясь TTS остальных.
- **Почему:** наивный последовательный пайплайн (TTS всех → encode всех) занимает в ~1.5 раза дольше.
- **Trade-off:** сложный concurrency-код, `as_completed` внутри другого `as_completed` — нетривиально читать.

### 8.8 Nuxt SPA (`ssr: false`) вместо полного Nuxt SSR
- **Решение:** фронт — чистая статика, рендерится в браузере.
- **Почему:** проще деплой (один HTML + JS), не нужен Node-сервер в продакшене. SEO для лендинга не критичен (B2B-продукт).
- **Trade-off:** медленнее «первый показ контента», нет server-side персонализации.

### 8.9 Pinia как слой состояния (мигрировали с `useState`)
- **Решение (обновлено):** глобальный state — на **Pinia** (`stores/auth.ts` и др.). Раньше был
  `useState('key', factory)`.
- **Почему:** с ростом приложения (auth, billing, comments, student) понадобились явные сторы с
  геттерами/экшенами вместо рантайм-синглтонов.
- **Trade-off:** одна зависимость. `composables/useCreationMode.ts` остался модулем констант, а не стором.

### 8.10 Аутентификация на httpOnly-куках + CSRF (мигрировали с localStorage)
- **Решение (обновлено):** токены живут в **httpOnly-куках**, защита от CSRF — double-submit
  (`csrf_token` non-httpOnly + заголовок `X-CSRF-Token`). Refresh ротируется семействами в Redis с
  детектом повторного использования.
- **Почему:** httpOnly недостижим для XSS-скрипта; раньше токены лежали в `localStorage` (XSS-уязвимо).
- **Trade-off:** нужен CSRF-механизм и аккуратные `path`/`samesite` у кук. Полная картина — в
  [AUTH_FLOW.md](AUTH_FLOW.md).

### 8.11 Миграции: авто в dev, отдельный шаг в проде
- **Решение:** `app/main.py:_ensure_schema_at_head` запускает `alembic upgrade head` на старте, **но только если `RUN_MIGRATIONS_ON_STARTUP=true`** (дефолт dev). Заменяет старый «бутстрап через `Base.metadata.create_all`», который рассинхронизировался с историей миграций.
- **Почему:** в dev удобно — перезапустил контейнер, схема актуальна. В проде авто-миграция на старте опасна (тяжёлая миграция роняет readiness-пробу; параллельные реплики гонятся за advisory-lock).
- **Trade-off (решено для прода):** `.env.prod` ставит `RUN_MIGRATIONS_ON_STARTUP=false`, а миграция выполняется one-shot сервисом `migrate` в `docker-compose.prod.yml` **до** роллапа приложения; упавшая миграция валит деплой, не трогая работающую версию. См. [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) §5.1.

---

## 9. Что обязательно понять с первой недели

1. **Async вне Celery, sync внутри Celery.** Не путай.
2. **`models/__init__.py` должен реэкспортировать новые модели**, иначе alembic не увидит.
3. **`alembic upgrade head` запускается автоматически** на старте — забыл сгенерировать миграцию = backend не стартует.
4. **`task_id` хранится в БД** (`analyze_task_id`, `video_task_id`), чтобы фронт мог продолжить poll'ить после refresh страницы.
5. **`creation_mode` определяет шаги пайплайна** — особенно пропуск VLM-summary в auto-режиме.
6. **AI-провайдер по умолчанию — облако Polza** (`.env.example`); локальный Ollama и Yandex AI Studio — альтернативы (env-правка, код тот же — OpenAI-совместимый клиент), и только для Ollama модели качаются вручную (`ollama pull ...`).
7. **CORS-порядок middleware** в `main.py` — CORS должен быть зарегистрирован *последним*, чтобы оказаться снаружи `log_and_catch` (см. длинный комментарий в файле).
8. **`__mapper_args__ = {"eager_defaults": True}`** на моделях с `onupdate=func.now()` — без этого `MissingGreenlet` при сериализации после `UPDATE`.

---

## 9b. Подсистемы, добавленные после MVP

Картинка выше — ядро. Поверх него выросли подсистемы, которых не было в первой версии этого
документа. Кратко (детали — в [DECISIONS.md](DECISIONS.md)):

| Подсистема | Где код | Суть |
|---|---|---|
| **Тесты/квизы** | `models/quiz.py`, `services/quiz_service.py`, `grading_service.py`, `routers/quiz_*` | Polymorphic-вопросы в JSONB, версионирование `quiz_questions` + pointer-snapshot в попытке, hybrid grading (детерминированный для closed + LLM для open). AI-генерация и AI-review вопросов. |
| **Биллинг/кредиты** | `models/credit.py`, `services/billing_service.py`, `routers/billing.py`, `constants.py` (`CREDIT_WEIGHTS`, `PLAN_CONFIGS`) | Кредитный счёт на пользователя: `balance` + `reserved`. Генерация резервирует кредиты (`RESERVE`) и списывает/возвращает по факту (`RELEASE`). Планы free/starter/pro/school, топапы. Админ-эндпоинты за `X-Admin-Token`. |
| **Email** | `services/email_service.py`, `email_token_service.py`, `tasks/email_pipeline.py`, `templates/email/` | Транзакционные письма (верификация, «видео готово») через Resend в отдельном воркере. Подписанные stateless-токены + одноразовое потребление через Redis. |
| **Soft-delete** | глоб. фильтр для `User`/`Lesson`, явный для `Course`; `tasks/purge_pipeline.py` | Архивация вместо `DELETE`; суточный `purge_soft_deleted` (beat в `celery_quiz`) физически удаляет строки и файлы спустя `SOFT_DELETE_PURGE_DAYS`. |
| **Комментарии** | `models/comment.py`, `services/comment_service.py`, `routers/comments.py` | Плоские (без вложенности) комментарии к урокам; teacher-владелец модерирует любые. |
| **Задания (assignments)** | `models/assignment.py`, `services/assignment_service.py`, `routers/assignment_teacher.py`/`assignment_student.py`, `file_validation_service.py`, `constants.py` (`ATTACHMENT_*`) | Текстовое задание + сдача студентом (текст и/или файлы), оценка с нормировкой в 0..1, приватный тред teacher↔student. Вложения только **хранятся**, не парсятся (whitelist MIME/расширений + лимиты размера/числа). Файлы сдач авто-удаляются через `ATTACHMENT_RETENTION_DAYS_AFTER_GRADED` после оценки (`purge_pipeline`). |
| **Публикация / видимость** | `services/visibility_service.py`, `routers/courses.py` (module publish), `routers/lessons.py` (lesson publish), `dependencies.py` (`require_lesson_access`) | Независимые флаги `is_published` на Course/Module/Lesson; студент видит урок только если опубликована **вся цепочка** (AND). Скрытие — read-time эффект (черновик → **404**, не 403). Снятие публикации родителя НЕ сбрасывает флаги детей. |
| **Версии видео урока** | `models/lesson_video.py`, `tasks/video_pipeline.py`, `routers/lessons.py` (`/videos`, `/videos/{id}/publish`) | Каждая успешная генерация создаёт строку `LessonVideo` (`is_published=False`). Учитель смотрит список версий и публикует одну (`POST /videos/{id}/publish`) — остальные снимаются, `lesson.video_url` синхронизируется. Прямая загрузка видео публикуется сразу. |
| **Журнал оценок / аналитика** | `services/gradebook_service.py`, `analytics_service.py`, `routers/gradebook.py`, `analytics.py` | Сводки по курсу/уроку, ручные override оценок, аналитика по квизам. |
| **S3-бэкенд хранилища** | `services/storage_service.py`, `signed_url_service.py`, `config.py` (`STORAGE_BACKEND`) | Хранилище переключается `local`↔`s3` (Yandex Object Storage/совместимое). При `local` отдаётся через `/files/*` с HMAC-подписанными URL; `files`-роутер регистрируется только в `local`-режиме. |
| **Наблюдаемость** | `main.py`, `celery_app.py`, `logging_config.py`, `monitoring/` | Sentry (FastAPI+Celery+SQLAlchemy), Prometheus-метрики (HTTP + Celery-сигналы) → Grafana, Flower для Celery, structlog с `request_id`. |
| **Платежи ЮKassa (hardened)** | `routers/billing.py`, `services/yookassa_service.py`, `webhook_security.py`, `tasks/payment_pipeline.py` | Вебхук проверяет source-IP (allowlist CIDR + доверенные прокси), телу не верит: ставит `process_yookassa_payment` в очередь и сразу отвечает 200. Задача re-fetch'ит платёж из API ЮKassa и проводит через **единый** `_settle_payment` (FOR UPDATE, анти-double-credit). Бэкстоп — beat-задача `reconcile_pending_payments` (15 мин) + алерт по зависшим (`Payment.alerted_at`). См. [DECISIONS.md](DECISIONS.md) §39–40. |
| **Стриминг видео** | `routers/lessons.py` (`/video/stream`, `/videos/{id}/stream`), `constants.py` (`VIDEO_XACCEL_*`) | Авторизованная отдача видео: S3 → 302 на presigned URL; local+nginx (прод) → `X-Accel-Redirect` на internal-префикс `/protected-media/`; dev → 302 на подписанный `/files/*`. Python в проде байты не гоняет. См. [DECISIONS.md](DECISIONS.md) §41. |
| **Дисковый GC** | `tasks/purge_pipeline.py` (`gc_disk_caches`, `gc_lesson_videos`), `constants.py` (`CACHE_GC_*`, `LESSON_VIDEO_GC_*`) | Ночные beat-задачи: TTL + size-cap LRU-эвикция `slides_cache`/`summaries_cache` (recency = mtime, бампается на cache-hit) и прунинг холодных неопубликованных `LessonVideo` (никогда не трогает опубликованные; у каждой задачи свой kill-switch). Кеши больше **не растут бесконечно**. |
| **Сброс/смена пароля** | `services/password_reset_service.py`, `models/password_reset_token.py`, `routers/auth.py` | `POST /auth/forgot-password` → одноразовый токен (в БД только hash, TTL 30 мин) → письмо через `celery_email` → `POST /auth/reset-password`; `POST /auth/change-password` для залогиненных. Страницы `forgot-password.vue`/`reset-password.vue`. |
| **Согласия при регистрации (152-ФЗ)** | `models/user.py` (`pdn_consent_at`, `marketing_consent*`, `consent_policy_version`, `consent_ip`), `schemas/auth.py` | Обязательные согласия (ПДн/оферта) валидируются при регистрации, версия документов фиксируется (`CONSENT_POLICY_VERSION`), маркетинговое — опционально. |
| **Preview «глазами студента»** | `routers/courses.py` (`GET /{id}/preview`), `stores/preview.ts`, `pages/courses/[id]/preview/` | Teacher-владелец смотрит курс/урок так, как его видит записанный студент (с учётом правила видимости), не записываясь на курс. |
| **Обложка курса** | `routers/courses.py` (`POST /{id}/cover`), `CourseCoverUpload.vue` | Загрузка изображения (≤5 MB) в `storage/covers/`; `CourseOut` несёт `cover_image_url` (загруженная) и `cover_url` (внешняя ссылка) — сериализатор предпочитает загруженную. |
| **TTS chunk-кеш** | `services/tts_service.py`, `constants.py` (`TTS_CHUNK_CACHE_*`) | Дисковый кеш WAV на уровне TTS-чанков (`storage/tts_chunk_cache/`, ключ — sha256 текста+голоса): правка одного предложения пересинтезирует только свой чанк, а не весь слайд. |
| **Checkpoint/resume пайплайна** | `tasks/video_pipeline.py` (Redis `job:{lesson_id}:checkpoint`) | Синтезированные слайды чекпоинтятся в Redis; при ошибке/отмене чекпоинт и `work_dir` сохраняются — повторный запуск переиспользует готовое. Кооперативная отмена: `POST /lessons/{id}/cancel-generation`. |
| **Startup-reconciliation** | `main.py` (`_reconcile_stuck_lessons`), `constants.py` (`STUCK_LESSON_GRACE_MINUTES`) | На старте backend уроки, зависшие в `analyzing`/`processing` дольше 120 мин (потерянный Celery-таск после flushdb/крэша), помечаются `error` — фронт не поллит вечно. |
| **Глубина раскрытия темы (`detail_level`)** | `models/lesson.py` (`DetailLevel`), `services/duration_service.py`, `llm_service.py` (`_SSML_DETAIL_OVERRIDE`), `services/vision_analysis.py` | Заменила целевую длительность (недостижимую на коротких деках). Три уровня (`brief`/`auto`/`high`) задают бюджет слов на слайд в auto-режиме и степень сжатия/дополнения авторского текста в manual-режиме; ожидаемая длительность и цена — производные, не вход. Вырожденный ответ vision-модели детектируется и ретраится один раз. См. [DECISIONS.md](DECISIONS.md) §57. |
| **База знаний** | `models/lesson_material.py` (`LessonMaterial` + `LessonNote`), `routers/lesson_materials.py`, `GET /courses/{id}/knowledge` в `routers/courses.py` | Преподаватель прикладывает файлы (методички) и пишет markdown-конспекты к уроку; студент видит их на вкладке урока. Без AI. Один роутер на обе сущности, гейты — уже существующие (`require_lesson_access`/`get_owned_lesson`/`require_course_access`); файлы только хранятся, свой лимит (30/2 ГБ на урок), без ретеншна. Охват шире одного урока: файлы из `/uploads/pptx` и `/uploads/script` регистрируются сюда автоматически (best-effort, не роняя загрузку); картинки и вложения в теле текстового урока — те же `LessonMaterial` с флагом `is_inline`, адресуемые из markdown как `material:{uuid}`; на уровне курса есть дерево модуль → урок → (материалы + метаданные конспектов) одним запросом, обрезаемое `visibility_service`. См. [DECISIONS.md](DECISIONS.md) §47 и §61. |
| **Метеринг AI-проверки и платное продление хранения** | `services/billing_service.py` (`QUIZ_GRADE`, `RETENTION_EXTEND`), `constants.py` (`AI_GRADING_FREE_ANSWERS_PER_MONTH`) | LLM-оценка открытых студенческих ответов бесплатна до месячной квоты (одинаковой на всех тарифах), сверх неё и продление хранения вложений сдач списываются тем же кредитным леджером, что видео. Деградация тихая: нет квоты/кредитов → ответ остаётся `needs_review`, сдача студента не блокируется. `POST /quiz/ai-review` (QA-проверка своего теста учителем) при этом убрана из-под кредитов и всегда бесплатна. См. [DECISIONS.md](DECISIONS.md) §48–49. |
| **Архивация курса** | `routers/students.py` (`enroll`), `tasks/purge_pipeline.py` (`_course_purge_guard`) | Архив (`DELETE /courses/{id}`) — teacher-facing: уже записанный студент не теряет доступ (правило видимости не включает `deleted_at`), новая запись на архивный курс — 404. `purge_soft_deleted` никогда не удаляет курс с хотя бы одной `Enrollment`, независимо от возраста — каскад иначе стёр бы чужой прогресс/оценки/сдачи. См. [DECISIONS.md](DECISIONS.md) §51. |
| **Подсистема уведомлений** | `services/notification_service.py` (нет отдельной таблицы — присутствие живёт в Redis `notify:presence:lesson:{id}`), `routers/notifications.py` | Единая точка входа для внутренних (в приложении) и почтовых уведомлений — urgent (сразу) и digest (батч), гейт присутствия по активному SSE-соединению (не шлёт urgent-email тому, кто уже смотрит прогресс в браузере). Заменила точечные email-шаблоны вроде `video_ready.html` (см. [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — старый шаблон осиротел). См. [DECISIONS.md](DECISIONS.md) §54. |
| **PPTX pre-processing + шрифтопак** | `services/video_service.py` (расширение `wrap="none"`-боксов), `backend/Dockerfile` (шрифты + телеметрия недостающих) | Перед LibreOffice текстовые боксы с `wrap="none"` программно раздвигаются под фактическую ширину текста — иначе LibreOffice обрезает однострочные надписи, которые PowerPoint показывал целиком. Отдельно: в образ докладывается шрифтопак и логируется телеметрия по шрифтам, которых не хватило при рендере слайда. См. [DECISIONS.md](DECISIONS.md) §55–56. |
| **Мобильная навигация** | `composables/useMobileMenu.ts`, `AppHeader.vue` | Один бургер на всех layout'ах (включая `bare`/`workspace`, где нет сайдбара): состояние в композабле (Escape, блокировка скролла, возврат фокуса), панель через `<Teleport to="body">`, пункты меню зеркалят `AppSidebar`/`StudentSidebar`. См. [DECISIONS.md](DECISIONS.md) §52. |
| **Zero-downtime деплой (blue-green)** | `deploy/deploy.sh`, `deploy/lib.sh`, `docker-compose.prod.yml` (слоты `backend_blue`/`backend_green` и т.п.) | Веб-слой катится в двух слотах; релиз поднимает свободный слот, ждёт healthy, переключает nginx-upstream (`nginx -s reload`) и только потом гасит старый — без простоя. Подробно, включая ручные операции и грабли, — [DEPLOYMENT.md](DEPLOYMENT.md) §7. См. [DECISIONS.md](DECISIONS.md) §53. |

---

## 10. Что читать дальше

- [DATA_FLOW.md](DATA_FLOW.md) — пошаговые сценарии для каждого ключевого UX.
- [AUTH_FLOW.md](AUTH_FLOW.md) — JWT, роли, как обрабатывается истечение токена.
- [DEPLOYMENT.md](DEPLOYMENT.md) — как поднять локально с нуля.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — где ходит технический долг.
- [DECISIONS.md](DECISIONS.md) — расширенная аргументация выбранных решений.
