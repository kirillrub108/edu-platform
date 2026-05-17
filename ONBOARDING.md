# Edu Platform — Onboarding Guide для нового разработчика

> Документ, который проведёт тебя от полного нуля до уверенного понимания всей системы. Читать сверху вниз. Если хочется — параллельно открывай файлы, на которые ссылается гайд.

---

## Оглавление

1. [High-Level Overview](#1-high-level-overview)
2. [Полная структура проекта](#2-полная-структура-проекта)
3. [Runtime / Data Flow](#3-runtime--data-flow)
4. [Backend, Database, API](#4-backend-database-api)
5. [Frontend / UI](#5-frontend--ui)
6. [Инфраструктура и деплой](#6-инфраструктура-и-деплой)
7. [Technical Debt и слабые места](#7-technical-debt-и-слабые-места)
8. [Engineering Knowledge Transfer](#8-engineering-knowledge-transfer)
9. [Learning Path](#9-learning-path-roadmap-изучения)
10. [Final Knowledge Test](#10-final-knowledge-test)

---

# 1. High-Level Overview

## 1.1 Что это за проект

**Edu Platform** — это SaaS для **автоматического создания видеолекций с помощью AI**.

Целевая аудитория — **преподаватели и онлайн-школы**, которым нужно превратить готовые слайды в полноценные видеоуроки без записи камеры, монтажа, актёров озвучки и видеоредакторов.

## 1.2 Какую проблему решает

Создание одной видеолекции «вручную» — это:
- запись аудио в студии (или дома, что плохо);
- монтаж видео под слайды;
- многократные перезаписи при правках в презентации;
- минимум 4–8 часов работы на 30 минут готового видео.

Платформа сжимает этот процесс до **«загрузил PPTX → нажал кнопку → через 2-5 минут получил MP4»**. Дополнительно — выкладывает курс студентам, считает их прогресс и тесты.

## 1.3 Архитектура — диаграмма (текстом)

```
                       ┌──────────────────────────────┐
                       │       Браузер (студент       │
                       │       или преподаватель)     │
                       └────────────┬─────────────────┘
                                    │  HTTP + JSON
                                    ▼
                       ┌──────────────────────────────┐
                       │  Frontend: Nuxt 3 SPA         │
                       │  (порт 3000, SSR=false)       │
                       └────────────┬─────────────────┘
                                    │  /api/v1/*  +  Bearer JWT
                                    ▼
        ┌───────────────────────────────────────────────────────┐
        │  Backend: FastAPI (порт 8000, ASGI/uvicorn)           │
        │  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
        │  │routers │→│dependencies│→│ services │→│  models   │ │
        │  └────────┘  └──────────┘  └──────────┘  └──────────┘ │
        │       │                      │                        │
        │       │ delay() ── задача    │ async SQL              │
        │       ▼                      ▼                        │
        │  ┌────────┐               ┌──────────────────┐        │
        │  │ Redis  │               │ PostgreSQL 17    │        │
        │  │ broker │               │ (asyncpg engine) │        │
        │  └───┬────┘               └──────────────────┘        │
        └──────┼────────────────────────────────────────────────┘
               │                              ▲
               │  task pickup                 │ sync engine (psycopg2)
               ▼                              │
        ┌──────────────────────────────────────────────────────┐
        │  Celery worker (prefork, 2 процесса)                 │
        │  app.tasks.video_pipeline /  app.tasks.vision_pipeline│
        │                                                      │
        │  Внешние сервисы, к которым обращается worker:       │
        │   • LibreOffice headless  (PPTX → PDF)               │
        │   • pdftoppm              (PDF → PNG, 150 DPI)       │
        │   • Vision LLM (Ollama / YandexGPT-Pro Vision)       │
        │   • Text LLM   (Ollama qwen / YandexGPT)             │
        │   • Silero TTS HTTP (порт 9898)                      │
        │   • FFmpeg (image+wav → MP4 сегмент → concat)        │
        └──────────────────────────────────────────────────────┘
                                    │
                                    ▼
                       ┌──────────────────────────────┐
                       │ Local storage:               │
                       │ /app/storage/{pptx,videos,   │
                       │ lessons/.../slides,          │
                       │ summaries_cache, slides_cache│
                       │ Раздаётся через FastAPI      │
                       │ /files/* (StaticFiles)       │
                       └──────────────────────────────┘
```

## 1.4 Основные модули

| Модуль | Где живёт | Что делает |
|---|---|---|
| **HTTP API** | [backend/app/routers/](backend/app/routers/) | принимает запросы, валидирует, дёргает сервисы и БД |
| **ORM-модели** | [backend/app/models/](backend/app/models/) | SQLAlchemy 2.x; описывают таблицы и связи |
| **Pydantic DTO** | [backend/app/schemas/](backend/app/schemas/) | валидация входа и сериализация ответа |
| **Сервисы** | [backend/app/services/](backend/app/services/) | бизнес-логика: LLM, TTS, video, storage, auth, vision |
| **Celery tasks** | [backend/app/tasks/](backend/app/tasks/) | долгие фоновые пайплайны (генерация видео, vision-анализ) |
| **Миграции** | [backend/alembic/versions/](backend/alembic/versions/) | эволюция схемы БД |
| **Frontend SPA** | [frontend/src/](frontend/src/) | Nuxt 3 (CSR), Tailwind, кабинеты teacher/student |
| **Silero TTS** | [silero/config.py](silero/config.py) | конфиг внешнего TTS-контейнера |
| **Инфра** | [docker-compose.yml](docker-compose.yml), `*/Dockerfile` | поднимает весь стек одной командой |

## 1.5 Технологии и почему именно они

| Технология | Версия | Зачем |
|---|---|---|
| **FastAPI** | 0.136 | async из коробки, авто-OpenAPI, лучшая dev-experience среди Python-фреймворков |
| **SQLAlchemy 2 (async)** | 2.0.49 | новый decl API + async-движок на asyncpg; ORM нужен для связей и каскадов |
| **PostgreSQL 17** | — | JSONB (опции квизов), уверенные транзакции, UUID, enum |
| **asyncpg + psycopg2** | dual driver | веб-часть async; Celery worker — sync (нет смысла в async внутри prefork-процесса) |
| **Celery + Redis** | 5.6 + 7 | стандарт для long-running задач в Python; видеогенерация занимает минуты — нельзя блокировать запрос |
| **Pydantic v2** | 2.13 | валидация и сериализация одной моделью; быстрее v1 |
| **Ollama / OpenAI SDK** | 1.107 | универсальный клиент для любых OpenAI-совместимых LLM (YandexGPT тоже эмулирует этот API) |
| **Silero TTS** | docker | бесплатный качественный русский TTS, OSS, работает локально |
| **LibreOffice headless** | — | единственный надёжный способ рендерить PPTX в PDF без потери шрифтов |
| **FFmpeg** | — | склейка `image + audio → MP4`, индустриальный стандарт |
| **Nuxt 3 (SPA)** | 3.14 | Vue + готовый роутинг + composables; SSR отключён, чтобы фронт был статикой |
| **Tailwind CSS** | 3.4 | утилитарный CSS — быстрый прототип без отдельных .css-файлов |
| **JWT (HS256)** | PyJWT 2.10 | stateless-аутентификация; пара access + refresh |
| **bcrypt + sha256** | 4.3 | bcrypt для паролей, sha256-обёртка нужна, потому что bcrypt режет пароль на 72 байта |

---

# 2. Полная структура проекта

## 2.1 Корень репозитория

```
edu-platform/
├── backend/              # FastAPI + Celery
├── frontend/             # Nuxt 3 SPA
├── silero/               # конфиг для контейнера silero-tts (внешний образ)
├── docker-compose.yml    # 5 сервисов: postgres, redis, silero-tts, backend, celery_worker, frontend
├── .env / .env.example   # секреты и параметры всего стека
├── pyrightconfig.json    # настройки type-checker'а
├── README.md             # короткая выжимка (этот гайд её расширяет)
└── .gitignore
```

## 2.2 Backend в деталях

```
backend/
├── Dockerfile                   # python:3.13-slim + libreoffice + ffmpeg + poppler + кириллические шрифты
├── alembic.ini                  # конфиг миграций
├── alembic/
│   ├── env.py                   # подключает Base.metadata из app.models
│   └── versions/                # 4 миграции: init → pptx_path → slide_texts → task_ids
├── lo-emoji-substitution.xcu    # mapping шрифтов эмодзи (Segoe→Noto) для LibreOffice
├── requirements.txt
├── storage/                     # местное файловое хранилище (volume в docker)
│   ├── pptx/                    # загруженные презентации
│   ├── videos/                  # готовые MP4
│   ├── lessons/<id>/slides/     # PNG слайдов после vision-анализа
│   ├── slides_cache/            # кеш PPTX→PNG (по hash содержимого + DPI)
│   ├── summaries_cache/         # кеш VLM-саммари (по sha256 PNG + provider/model)
│   └── video_jobs/<lesson_id>/  # временная директория одного джоба (удаляется в finally)
└── app/
    ├── __init__.py
    ├── main.py                  # FastAPI инстанс, CORS, lifespan, exception handlers
    ├── config.py                # pydantic-settings; читает .env
    ├── database.py              # async engine, AsyncSessionLocal, get_db, Base
    ├── dependencies.py          # get_current_user, require_teacher, require_student
    ├── celery_app.py            # инстанс Celery + конфиг
    ├── models/                  # SQLAlchemy ORM
    │   ├── __init__.py          # реэкспорт всех моделей (важно для alembic --autogenerate)
    │   ├── user.py              # User + UserRole(enum)
    │   ├── course.py            # Course + AccessMode(enum)
    │   ├── lesson.py            # Module, Lesson, QuizQuestion + Content/LessonStatus/CreationMode
    │   ├── enrollment.py        # Enrollment + LessonProgress
    │   └── slide_text.py        # SlideText (per-slide narration)
    ├── schemas/                 # Pydantic v2 DTO
    │   ├── auth.py              # UserRegister, UserLogin, TokenResponse, RefreshRequest
    │   ├── user.py              # UserOut, UserBase
    │   ├── course.py            # CourseCreate/Update/Out/Detail, ModuleCreate/Out, LessonShort
    │   ├── lesson.py            # LessonCreate/Update/Out, ScriptUpdateRequest, VideoGenerateRequest, TaskStatusResponse
    │   └── slide.py             # SlideTextOut/Update, SlideListResponse, AnalyzeStatusResponse
    ├── routers/                 # HTTP endpoints (все под префиксом /api/v1)
    │   ├── auth.py              # /auth/register, /login, /refresh, /me
    │   ├── courses.py           # /courses CRUD + /modules + /publish (только teacher)
    │   ├── lessons.py           # /lessons CRUD + /script + /generate-video + /task-status
    │   ├── slides.py            # /lessons/{id}/analyze + /slides + PATCH/regenerate
    │   ├── uploads.py           # /uploads/pptx, /uploads/script, /uploads/video
    │   └── students.py          # /students/enroll, /my-courses, /complete, /quiz-result
    ├── services/                # бизнес-логика, переиспользуемая везде
    │   ├── auth_service.py      # hash_password / verify_password / JWT encode-decode
    │   ├── llm_service.py       # OpenAI-совместимый клиент: SSML-split, enhance, quiz
    │   ├── tts_service.py       # обёртка вокруг Silero HTTP + чанкинг + очистка SSML
    │   ├── storage_service.py   # save_upload, get_url, get_full_path, delete
    │   ├── video_service.py     # PPTX→PNG, encode_segment (FFmpeg), concat
    │   └── vision_analysis.py   # Ollama/Yandex vision: analyze_slide, summarize_slide (+ кеш)
    ├── tasks/                   # Celery — единственное место, где логика «долгая»
    │   ├── video_pipeline.py    # generate_video_lesson (главный пайплайн)
    │   └── vision_pipeline.py   # analyze_presentation_task (vision-mode)
    ├── utils/
    │   └── slide_renderer.py    # альтернативный пайплайн PPTX→PDF→PNG (через pdf2image)
    ├── tests/                   # пусто (TODO)
    └── .stubs/                  # заглушки типов для pyright
```

### Что нельзя ломать

| Файл / папка | Почему критично |
|---|---|
| `app/database.py: Base = declarative_base()` | от него наследуются все модели; смена → ломает alembic autogenerate |
| `app/celery_app.py: include=[...]` | Celery обнаруживает задачи только из явно перечисленных модулей |
| `app/models/__init__.py` | `alembic env.py` импортирует `app.models` целиком; новая модель без реэкспорта = миграция её не увидит |
| `app/main.py` lifespan | при старте автоматически прогоняет `alembic upgrade head` — заменяет старый `Base.metadata.create_all` |
| `app/main.py` CORS-порядок | CORS должен быть **первым** middleware, иначе ошибки 500 не получат CORS-заголовков (см. длинный комментарий в файле) |
| `lo-emoji-substitution.xcu` | без него LibreOffice падает на PPTX с эмодзи (Segoe Emoji не установлен) |
| `storage/` volume | если потереть — потеряете загруженные PPTX, готовые MP4 и кеши |
| `_sync_url` в `tasks/video_pipeline.py` | Celery работает синхронно → нужен `psycopg2`, а не `asyncpg` |

## 2.3 Frontend в деталях

```
frontend/
├── Dockerfile               # node:22-alpine + копия node_modules в /opt/node_modules_baked
├── docker-entrypoint.sh     # сидит node_modules в bind-mount если он пуст (для VS Code)
├── nuxt.config.ts           # ssr:false, srcDir: 'src/', polling для HMR в Docker
├── tailwind.config.ts       # цвета, тени, brand
├── package.json             # nuxt + lucide-vue-next + tailwind
└── src/
    ├── app.vue              # корневой компонент: <NuxtLayout><NuxtPage/></NuxtLayout>
    ├── layouts/
    │   ├── default.vue      # Header + max-w-6xl контейнер
    │   └── bare.vue         # без header (используется на лендинге и dashboard)
    ├── middleware/
    │   ├── auth.ts          # подгружает /auth/me; редиректит на /login если 401
    │   └── teacher.ts       # student → /student/dashboard, teacher → пропускает
    ├── composables/
    │   ├── useApi.ts        # обёртка над $fetch с Bearer-токеном; авто-логаут на 401
    │   ├── useAuth.ts       # login/register/logout/fetchMe + useState('auth.user')
    │   └── useCreationMode.ts  # 4 режима + декларативные карточки CREATION_MODE_CARDS
    ├── pages/               # файловый роутинг Nuxt
    │   ├── index.vue        # лендинг
    │   ├── login.vue
    │   ├── register.vue
    │   ├── dashboard.vue    # teacher: список курсов
    │   ├── courses/
    │   │   ├── index.vue    # (тривиальный)
    │   │   ├── create.vue   # форма «новый курс»
    │   │   └── [id].vue     # курс: модули → уроки + публикация
    │   ├── lessons/
    │   │   └── [id].vue     # ★ ЦЕНТРАЛЬНАЯ страница: загрузка PPTX, режимы, генерация
    │   └── student/
    │       ├── dashboard.vue        # «мои курсы» + ввод access-кода
    │       └── courses/[id].vue     # плеер уроков
    └── components/
        ├── AppHeader.vue         # лого + аватар + logout
        ├── AppSidebar.vue        # боковое меню (на teacher dashboard)
        ├── CourseCard.vue        # карточка курса в гриде
        ├── CreationModeChooser.vue  # 4 карточки выбора creation mode
        ├── LessonPlayer.vue      # video-плеер для студента
        ├── PipelineStages.vue    # шаги пайплайна с прогрессом (slides→summary→llm→tts→encoding)
        ├── ProgressBar.vue       # тонкий бар c label
        ├── SkeletonCard.vue      # placeholder при загрузке
        ├── SlideTextEditor.vue   # ★ редактор текстов слайдов с превью PNG, навигацией, регенерацией
        ├── StatusBadge.vue       # цветной бейдж по статусу урока
        ├── UiButton.vue          # primary/secondary/ghost/danger × sm/md/lg + loading
        └── UiInput.vue
```

### Где что искать

| Задача | Куда смотреть |
|---|---|
| API-вызов | `composables/useApi.ts` (общая обёртка) + `pages/.../[id].vue` (использование) |
| Auth-флоу | `composables/useAuth.ts` + `middleware/auth.ts` |
| Business-логика урока | `pages/lessons/[id].vue` (огромный файл — это «пульт управления уроком») |
| UI-кит | `components/Ui*.vue` |
| Состояние через сессии | `useState('key', () => ...)` — глобальный state Nuxt |

---

# 3. Runtime / Data Flow

## 3.1 Что происходит при запуске

```
docker-compose up
   │
   ├── postgres   ── healthcheck (pg_isready)
   ├── redis      ── требует пароль из env
   ├── silero-tts ── скачивает модель v5_5_ru.pt при первом старте
   │
   ├── backend (depends_on: postgres healthy, redis, silero-tts)
   │      │
   │      └── uvicorn app.main:app
   │             │
   │             ├── lifespan startup:
   │             │     1. SELECT 1 — проверка БД
   │             │     2. alembic upgrade head — миграция до последней версии
   │             │
   │             └── готов слушать :8000
   │
   ├── celery_worker (depends_on: backend, redis, silero-tts)
   │      │
   │      └── celery -A app.celery_app worker --pool=prefork -c 2
   │             │
   │             └── 2 процесса слушают очередь "celery" в Redis
   │
   └── frontend (depends_on: backend)
          │
          ├── docker-entrypoint.sh — сидит node_modules если bind-mount пустой
          └── nuxt dev --host 0.0.0.0  →  :3000
```

**Нюанс №1 — миграции при старте.** В `app/main.py:_ensure_schema_at_head()` явно дёргается `alembic command.upgrade(cfg, "head")`. Это заменяет старый `Base.metadata.create_all`, который не оставлял версии в alembic_version и ломал последующие autogenerate-миграции.

**Нюанс №2 — два движка SQLAlchemy.**
- Web-сторона использует `create_async_engine(...asyncpg...)` (`app/database.py`).
- Celery worker использует **синхронный** `create_engine(...psycopg2...)` (`app/tasks/video_pipeline.py:_sync_url`).

Так сделано потому что Celery prefork-воркер сам не async — каждый таск выполняется в отдельном процессе. Async внутри него не даст пользы и усложнит код.

## 3.2 Жизненный цикл HTTP-запроса

Пример: `POST /api/v1/courses/`.

```
Browser → CORS preflight (OPTIONS)
   │
   ▼
CORSMiddleware (внешний)        ← добавляет Access-Control-Allow-Origin
   │
   ▼
log_and_catch middleware        ← логирует, ловит Exception → JSONResponse(500)
   │                              (важно: внутри CORS, чтобы 500 тоже имел CORS-заголовки)
   ▼
ExceptionMiddleware (Starlette) ← пропускает HTTPException через @app.exception_handler
   │
   ▼
APIRouter("/api/v1/courses")    ← routers/courses.py
   │
   ▼
Depends(require_teacher)
   │
   ├─ Depends(get_current_user)
   │    ├─ HTTPBearer → читает заголовок "Authorization: Bearer <token>"
   │    ├─ decode_token → проверка подписи, exp, type=="access"
   │    └─ db.get(User, UUID(sub)) → если нет/inactive → 401
   │
   └─ user.role == teacher? → если нет → 403
   │
   ▼
Depends(get_db) → AsyncSession (открывается, yield, закрывается в finally)
   │
   ▼
Тело хендлера (await db.commit() и т.д.)
   │
   ▼
Pydantic response_model → сериализация → JSON
```

## 3.3 Auth — детали

- **Регистрация и логин** возвращают `access_token` + `refresh_token`.
- Оба — **JWT HS256**, подписаны `SECRET_KEY`. В payload: `{sub, email, role, type, exp}`.
- Access — 15 минут, refresh — 120 дней (см. `.env`).
- Frontend кладёт оба в **localStorage** под ключами `access_token` / `refresh_token`.
- **Обновление access** происходит при каждом 401: `POST /auth/refresh` с телом `{refresh_token}` → новый access + refresh (sliding window).
- `useApi` автоматически добавляет `Authorization: Bearer <access>` к каждому запросу.

## 3.4 Главный data-flow: «преподаватель создаёт видеолекцию»

Самый важный сценарий — лучше всего проследить пошагово.

### Сценарий A: режим `presentation_and_text` (есть PPTX + есть текст доклада)

```
[Browser]                        [FastAPI]                    [Postgres]               [Celery worker]               [внешние]
   │
   ├─ POST /api/v1/courses ────► routers/courses ──── INSERT course ──┐
   │◄── 201 Created CourseOut ──────────────────────────────────────  │
   │                                                                  │
   ├─ POST /modules ──────────► INSERT module                         │
   │                                                                  │
   ├─ POST /lessons/ ─────────► INSERT lesson (status=draft)          │
   │                                                                  │
   ├─ POST /uploads/pptx ──────►                                      │
   │   FormData(file, lesson_id)                                      │
   │   storage_service.save_upload                                    │
   │     ├── /app/storage/pptx/<uuid>_orig.pptx                       │
   │   UPDATE lesson.pptx_path                                        │
   │◄── {file_path, file_url}                                         │
   │                                                                  │
   ├─ PUT /lessons/{id}/script ───► UPDATE lesson.script              │
   │                                                                  │
   ├─ POST /lessons/{id}/generate-video                               │
   │       body: {voice="xenia"}                                      │
   │   generate_video_lesson.delay(lesson_id, pptx_path, voice)       │
   │       └── publishes message to Redis queue ─────────►            │
   │   UPDATE lesson.video_task_id = task.id                          │
   │◄── {task_id, lesson_id}                                          │
   │                                                                  │
   │                                          ┌────────── consumes ───┘
   │                                          ▼
   │                                  generate_video_lesson()
   │                                   │
   │                                   ├── _set_status(processing)
   │                                   │
   │                                   ├── 1. video_service.convert_pptx_to_images
   │                                   │      cache check (md5 of file + DPI)
   │                                   │      hit?  → return cached PNGs (skip 30s)
   │                                   │      miss? ┌─ libreoffice → PDF
   │                                   │            └─ pdftoppm    → PNG @150dpi
   │                                   │      progress: ("slides", N, N)
   │                                   │
   │                                   ├── 2. (skipped в auto mode) summarize_presentation
   │                                   │      каждый PNG → vision LLM (ollama qwen2.5vl:7b)
   │                                   │      sha256(png)+model — кеш на диск
   │                                   │      progress: ("summary", k, N), parallel=4
   │                                   │
   │                                   ├── 3. llm_service.split_and_annotate_ssml
   │                                   │      prompt: "split text into N chunks aligned with slides,
   │                                   │               clean meta-tokens, convert digits to words,
   │                                   │               wrap in <p>/<break>/<prosody> SSML"
   │                                   │      response: JSON {"chunks": ["<p>...</p>", ...]}
   │                                   │      validation: len==N? всё непустое? → fallback по предложениям
   │                                   │      progress: ("llm", 1, 1)
   │                                   │
   │                                   ├── 4. TTS + encoding в ДВА thread-pool параллельно
   │                                   │      tts_pool (4 workers) → silero http /process?INPUT_TEXT=...
   │                                   │      enc_pool (3 workers) → ffmpeg -loop 1 -i PNG -i WAV ... .mkv
   │                                   │      приём: как только tts слайда K готов — сразу запускается encode K,
   │                                   │              не дожидаясь tts(K+1..N)
   │                                   │      progress: ("tts", k, N) и ("encoding", k, N)
   │                                   │
   │                                   ├── 5. video_service.concatenate_segments
   │                                   │      ffmpeg -f concat -c copy ... → /storage/videos/<lesson>.mp4
   │                                   │      (stream-copy без перекодирования = быстро)
   │                                   │
   │                                   ├── _set_status(published, video_url=/files/videos/...)
   │                                   │
   │                                   └── finally: rmtree(work_dir)  — освобождаем место
   │
   │ (параллельно с пайплайном)
   ├─ GET /lessons/{id}/task-status/{task_id} (polling каждые 3с)
   │     AsyncResult(task_id).status
   │     если PROGRESS → result.info = {step, done, total}
   │     если ready    → result.result = {"status": "ok", "video_url": "..."}
   │
   ▼
показывает MP4 в <video src="...">
```

### Сценарий B: режим `presentation_auto` (PPTX без текста, vision LLM пишет текст)

Отличается тем, что **до** генерации видео вызывается отдельный пайплайн:

```
POST /api/v1/lessons/{id}/analyze
   │
   └── analyze_presentation_task.delay(...)
        │
        ├── PPTX → PNG (тот же кеш)
        ├── удалить старые SlideText для урока
        ├── для каждого слайда: создать SlideText(image_path=..., generated_text="")
        ├── vision_analysis_service.analyze_presentation(...)  ← ПОСЛЕДОВАТЕЛЬНО
        │     каждый слайд анализируется в контексте предыдущих 3 (для связности)
        │     прогресс ("vision", k, N)
        ├── записать generated_text в каждый SlideText
        ├── lesson.status = ready_for_edit
```

После этого фронт показывает `SlideTextEditor.vue` — превью PNG + textarea с авто-сохранением. Преподаватель правит, кликает «Генерировать видео» → запускается тот же `generate_video_lesson`, но он понимает, что есть `SlideText` строки и **не вызывает LLM-split** (использует тексты как есть, оборачивая в `<p>...</p>`).

## 3.5 Lifecycle урока (state machine)

```
       ┌──────────┐
       │  draft   │ ← создан POST /lessons/
       └────┬─────┘
            │ POST /lessons/{id}/analyze (только в auto-mode)
            ▼
       ┌──────────┐
       │analyzing │ ─── при ошибке ──► error
       └────┬─────┘
            │ vision_pipeline finished
            ▼
       ┌─────────────────┐
       │ ready_for_edit  │ ← teacher правит SlideText, потом → generate-video
       └────┬────────────┘
            │  ┌──────────────────────────────────┐
            ▼  ▼                                  │
       ┌──────────┐                               │
       │processing│ ─── при ошибке ──► error      │
       └────┬─────┘                               │
            │ video_pipeline finished             │
            ▼                                     │
       ┌──────────┐                               │
       │published │ ── повторный generate-video ──┘
       └──────────┘
```

В manual-режиме (`presentation_and_text`): `draft → processing → published`.
В auto-режиме: `draft → analyzing → ready_for_edit → processing → published`.

## 3.6 Self-check

- Где именно происходит переход `draft → processing`? (Ответ: в `tasks/video_pipeline.py:_set_status`.)
- Что произойдёт, если упадёт LibreOffice? (Ответ: `_run` выбросит RuntimeError → except в задаче → `_set_status(error)`, `finally rmtree(work_dir)`.)
- Почему в Celery используется `psycopg2`, а не `asyncpg`?
- Что случится, если очистить Redis на горячую? (Ответ: текущие задачи продолжатся в воркерах, но новые `delay()` потеряются до восстановления; статусы pending-задач будут недоступны через `AsyncResult`.)

---

# 4. Backend, Database, API

## 4.1 Database Schema

```
┌──────────────────────────┐
│ users                    │
├──────────────────────────┤
│ id           UUID  PK    │
│ email        str   UNIQ  │
│ hashed_password str       │
│ full_name    str?         │
│ role         enum (teacher|student) │
│ is_active    bool         │
│ created_at, updated_at    │
└──────────┬────────────┬───┘
           │1:N         │1:N
           ▼            ▼
┌────────────────────┐  ┌─────────────────────────────────────┐
│ courses            │  │ enrollments                         │
├────────────────────┤  ├─────────────────────────────────────┤
│ id          UUID PK│  │ id              UUID PK              │
│ title       str    │  │ student_id      FK users(CASCADE)   │
│ description text?  │  │ course_id       FK courses(CASCADE) │
│ cover_url   str?   │  │ enrolled_at     ts                  │
│ owner_id    FK users(CASCADE) │  │  UNIQUE(student_id, course_id) │
│ access_mode enum(link|code|invite)│└──────────┬──────────────────────────┘
│ access_code str?   │             │1:N
│ is_published bool  │             ▼
│ created_at, updated_at │  ┌─────────────────────────────────┐
└────────┬───────────┘     │ lesson_progress                 │
         │1:N              ├─────────────────────────────────┤
         ▼                 │ id              UUID PK          │
┌────────────────────┐     │ enrollment_id   FK enrollments  │
│ modules            │     │ lesson_id       FK lessons      │
├────────────────────┤     │ is_completed    bool             │
│ id           UUID PK│    │ quiz_score      float?           │
│ course_id    FK courses(CASCADE) │ │ completed_at    ts?              │
│ title        str   │     └─────────────────────────────────┘
│ order        int   │
│ created_at         │
└────────┬───────────┘
         │1:N
         ▼
┌──────────────────────────────────┐
│ lessons                          │
├──────────────────────────────────┤
│ id              UUID PK           │
│ module_id       FK modules(CASCADE)│
│ title           str              │
│ order           int              │
│ content_type    enum(video|text|quiz)│
│ pptx_path       str?             │ ← путь относительно storage/
│ video_url       str?             │ ← полный URL для <video src=>
│ text_content    str?             │
│ script          str?             │ ← текст доклада (manual mode)
│ creation_mode   enum             │ ← presentation_and_text|presentation_auto|text_only|prompt
│ status          enum             │ ← draft|analyzing|ready_for_edit|processing|published|error
│ analyze_task_id str?(64)         │ ← Celery task для resume polling
│ video_task_id   str?(64)         │ ← Celery task для resume polling
│ created_at, updated_at           │
└────┬──────────────────────┬──────┘
     │1:N                   │1:N
     ▼                      ▼
┌─────────────────────┐  ┌─────────────────────────────────┐
│ quiz_questions      │  │ slide_texts                     │
├─────────────────────┤  ├─────────────────────────────────┤
│ id        UUID PK   │  │ id              UUID PK         │
│ lesson_id FK lessons│  │ lesson_id       FK lessons      │
│ question  text      │  │ slide_number    int              │
│ options   JSONB     │  │ generated_text  text             │ ← результат vision LLM
│ correct_index int   │  │ edited_text     text?           │ ← правки преподавателя
│ order     int       │  │ image_path      str?            │ ← PNG слайда в storage
└─────────────────────┘  │ created_at, updated_at          │
                         │ UNIQUE(lesson_id, slide_number) │
                         └─────────────────────────────────┘
```

### Заметки по схеме

- **Все каскады `ondelete=CASCADE`.** Удалил пользователя → все его курсы, модули, уроки, слайды, прогрессы тоже улетели. Безопасно для GDPR-удаления, опасно при «удалил по ошибке».
- **`pptx_path` хранит относительный путь** (`pptx/<uuid>_file.pptx`), а **`video_url` — полный URL** (`http://localhost:8000/files/videos/<uuid>.mp4`). Эта несимметрия — историческая (раньше всё было относительным). Best practice — всегда конвертировать через `storage_service.get_url(rel_path)` в момент ответа.
- **`access_code` не уникален в схеме.** Если два преподавателя сгенерируют одинаковый код — `enroll(access_code=...)` найдёт первый попавшийся. Технический долг.
- **`SlideText` UNIQUE(lesson_id, slide_number)** — гарантирует, что после re-analyze не будет дублей.
- **JSONB для quiz options** — даёт гибкость (любое число опций, мульти-выбор позже), за счёт потери типизации на уровне БД.

## 4.2 Эндпоинты — справка

Все под префиксом `/api/v1`. Все, кроме auth, требуют `Authorization: Bearer <access>`.

### Auth (`routers/auth.py`)
| Метод | Путь | Тело | Возврат | Кто |
|---|---|---|---|---|
| POST | /auth/register | `{email, password, full_name?, role}` | `TokenResponse` | анон |
| POST | /auth/login | `{email, password}` | `TokenResponse` | анон |
| POST | /auth/refresh | `{refresh_token}` | `TokenResponse` | анон (с refresh) |
| GET  | /auth/me | — | `UserOut` | любой залогиненный |

### Courses (`routers/courses.py`) — только teacher
| Метод | Путь | Возврат |
|---|---|---|
| GET | /courses/ | список своих курсов |
| POST | /courses/ | создать |
| GET | /courses/{id} | курс с модулями и уроками (selectinload) |
| PUT | /courses/{id} | обновить (partial — `exclude_unset=True`) |
| DELETE | /courses/{id} | 204, каскадно удаляет всё |
| POST | /courses/{id}/modules | создать модуль |
| PUT | /courses/{id}/publish | toggle is_published |

### Lessons (`routers/lessons.py`) — только teacher
| Метод | Путь | Что делает |
|---|---|---|
| POST | /lessons/ | создать урок (нужен `module_id`) |
| GET | /lessons/{id} | детали урока |
| PUT | /lessons/{id} | partial update |
| DELETE | /lessons/{id} | удалить |
| PUT | /lessons/{id}/script | обновить текст доклада |
| POST | /lessons/{id}/generate-video | запустить пайплайн → возвращает `task_id` |
| GET | /lessons/{id}/task-status/{task_id} | poll статуса; meta = `{step, done, total}` |

### Slides (`routers/slides.py`) — только teacher, vision-режим
| Метод | Путь | Что делает |
|---|---|---|
| POST | /lessons/{id}/analyze | запуск vision-анализа PPTX |
| GET | /lessons/{id}/analysis-status/{task_id} | poll статуса анализа |
| GET | /lessons/{id}/slides | список SlideText (с image_url) |
| PATCH | /lessons/{id}/slides/{slide_id} | сохранить `edited_text` |
| POST | /lessons/{id}/slides/{slide_id}/regenerate | перегенерировать один слайд через vision LLM (с контекстом предыдущих 3) |

### Uploads (`routers/uploads.py`) — только teacher
| Метод | Путь | Принимает | Возвращает |
|---|---|---|---|
| POST | /uploads/pptx?lesson_id=... | multipart `file` (.pptx/.ppt/.pdf) | `{file_path, file_url}` |
| POST | /uploads/script?lesson_id=... | multipart `file` (.txt/.md/.pdf/.docx/.doc/.rtf/.odt/.html) | `{script, chars}` |
| POST | /uploads/video | multipart `file` (.mp4/.webm/.mov) | `{file_path, file_url}` |

> Извлечение текста из docs реализовано через зоопарк библиотек: `pypdf`, `python-docx`, `striprtf`, `odfpy`, кастомный `HTMLParser`, и `.doc` → LibreOffice headless.

### Students (`routers/students.py`) — только student
| Метод | Путь | Что делает |
|---|---|---|
| POST | /students/enroll | enroll по `course_id` или `access_code` |
| GET | /students/my-courses | список курсов |
| GET | /students/courses/{id} | детали курса (только если enrolled) |
| POST | /students/lessons/{id}/complete | пометить пройденным |
| POST | /students/lessons/{id}/quiz-result | сохранить score (≥0.6 → автоматически complete) |

## 4.3 Validation, error handling, caching

- **Валидация:** Pydantic v2 в `schemas/`. Например, голос ограничен regex `^(aidar|baya|kseniya|xenia|eugene)$`. Ошибки → 422 с массивом `errors()`.
- **Authorization:** трёхслойная — `HTTPBearer` (есть ли токен), `decode_token` (валиден ли), `require_teacher/student` (правильная ли роль). Принцип: каждый router-эндпоинт **сам** проверяет владение объектом (`_get_owned_lesson`, `_get_owned_course`).
- **Caching:**
  - **slides_cache** — md5 содержимого PPTX + DPI → готовые PNG. Re-генерация одного и того же PPTX занимает ~5 секунд вместо 30.
  - **summaries_cache** — sha256 PNG + provider/model → текстовое саммари VLM. Перегенерация лекции с правленными слайдами → не трогает уже видные слайды.
- **Error handling:**
  - HTTPException — кастомный handler (`{"detail": str}`).
  - RequestValidationError — 422 + raw errors.
  - Любое прочее — middleware `log_and_catch` логирует stack-trace и возвращает 500. **CORS заголовки сохраняются** благодаря порядку middleware (см. длинный комментарий в `main.py`).

## 4.4 Trade-offs архитектуры

| Решение | Плюс | Минус |
|---|---|---|
| Local file storage | просто, быстро на dev | не масштабируется, нет CDN; нужна миграция в S3 для прода |
| `prepare_with(StaticFiles, check_dir=False)` для раздачи | zero-config | в проде нужно отдавать nginx-ом (FastAPI не предназначен для статики под нагрузкой) |
| Redis = брокер + result backend | один сервис | потеря Redis = потеря всех результатов задач |
| Один Celery worker на всё | проще операционка | анализ блокирует генерацию видео, и наоборот |
| LibreOffice для PPTX→PDF | надёжный конвертер с поддержкой шрифтов | тяжёлый: 500MB образ, медленный старт |
| Vision LLM локально (Ollama) | бесплатно, без VPN | требует GPU/много RAM, плохая стабильность качества |
| Двойной движок async/sync БД | каждая сторона использует оптимальный | две точки настройки connection pool |

## 4.5 Self-check

- Какой эндпоинт вернёт 403 если ты teacher, но пытаешься enroll? Что нужно изменить?
- Что произойдёт, если стереть `slides_cache/<hash>/` пока пайплайн работает?
- Можно ли запустить generate-video без предварительной загрузки PPTX? (Ответ: нет, 400 «pptx_path is required».)

---

# 5. Frontend / UI

## 5.1 Архитектура Nuxt 3

- **`prerender: true (SSG at build time) на /`**
- **`ssr: false`** → это SPA. Всё рендерится в браузере. Сервер Nuxt существует только для dev-сервера и сборки.
- **`srcDir: 'src/'`** → нестандартное расположение, читай конфиг чтобы не путаться.
- **File-based routing**: `pages/lessons/[id].vue` → `/lessons/abc-123`.
- **Auto-imports**: `useApi`, `useAuth`, `ref`, `onMounted`, компоненты из `components/` — всё доступно без import.
- **Composables** живут в `composables/` и работают через `useState(key, factory)` — это **глобальный реактивный state** Nuxt (расшаренный между компонентами).

## 5.2 Routing и middleware

```
/                           → index.vue            (лендинг, layout=bare)
/login, /register           → формы
/dashboard                  → teacher (auth + teacher middleware)
/courses/create             → teacher
/courses/{id}               → teacher (модули + уроки)
/lessons/{id}               → teacher (★ главная рабочая страница)
/student/dashboard          → student (только auth)
/student/courses/{id}       → student (плеер)
```

**Middleware** объявляются в `definePageMeta({ middleware: ['auth', 'teacher'] })`. Применяются по порядку.

`middleware/auth.ts` — асинхронный, дёргает `/auth/me`. Если токен битый/нет — `navigateTo('/login')`.
`middleware/teacher.ts` — синхронный, проверяет роль уже **загруженного** user.

## 5.3 State management

**Никакой Pinia/Vuex.** Используется встроенный механизм Nuxt:

```ts
// composables/useAuth.ts
const user = useState<UserOut | null>('auth.user', () => null)
```

`useState('auth.user', factory)` создаёт реактивный синглтон по ключу. Все компоненты видят одно и то же значение. Это упрощает код, но плохо масштабируется на крупные приложения — при росте сложности придётся переходить на Pinia.

## 5.4 API-клиент

Один файл — `composables/useApi.ts`:

```ts
const apiFetch = async <T>(path, options = {}) => {
  const headers = { ...options.headers }
  const token = localStorage.getItem('access_token')
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    return await $fetch<T>(path, { baseURL: base, ...options, headers })
  } catch (err) {
    if (err?.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      await navigateTo('/login')
    }
    throw err
  }
}
```

**Замечания:**
- `localStorage` — XSS-уязвимое хранилище. Для прода стоит мигрировать на httpOnly cookie + CSRF.
- **Refresh-флоу не реализован.** При истечении access (через 30 минут) пользователь молча редиректится на `/login`, теряя текущую страницу. Refresh-токен лежит в localStorage без использования.

## 5.5 Ключевые компоненты

### `pages/lessons/[id].vue` — «пульт управления»

Это самая сложная страница в проекте (~640 строк). Содержит:
1. Заголовок урока + бейдж статуса.
2. `CreationModeChooser` — выбор режима.
3. Загрузка PPTX (multipart upload).
4. Текст доклада (manual mode):
   - textarea с подсчётом слов;
   - upload file → backend извлекает текст → подставляет в textarea.
5. Vision-анализ (auto mode):
   - кнопка «Запустить анализ» → POST `/analyze` → возвращает `task_id`;
   - polling каждые 2с через `/analysis-status/{task_id}`;
   - после успеха показывает `SlideTextEditor`.
6. Generate Video:
   - выбор голоса;
   - `PipelineStages` показывает где сейчас пайплайн (slides → summary → llm → tts → encoding);
   - polling каждые 3с.
7. `<video>` с готовым MP4.

**Тонкость polling:** есть **два** уровня polling-логики:
- если есть `task_id` — поллим Celery `AsyncResult`;
- если страница перезагружена и `task_id` не сохранён в lesson — поллим `GET /lessons/{id}` и смотрим на `lesson.status`.

Для этого в БД хранится `analyze_task_id` и `video_task_id` — чтобы пользователь мог обновить страницу и продолжить смотреть прогресс.

### `components/SlideTextEditor.vue` — редактор слайдов

- слева: PNG слайда (превью);
- справа: textarea с текстом озвучки;
- внизу: thumbnail-стрипа всех слайдов с маркером прогресса;
- авто-сохранение через debounce 500ms;
- регенерация через vision LLM (с контекстом 3 предыдущих);
- горячие клавиши: `Ctrl+Enter` → следующий слайд; `Ctrl+S` → сохранить.

### `components/PipelineStages.vue`

Stepper с этапами. Подсвечивает текущий шаг + крутилку. Шаги адаптируются: в auto-mode пропускается `summary` (тексты слайдов уже есть в БД).

## 5.6 Async logic patterns

Везде используется паттерн:
```ts
const loading = ref(true)
const error = ref('')

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiFetch(...)
  } catch (e) {
    error.value = e?.data?.detail ?? 'дефолт'
  } finally {
    loading.value = false
  }
}
onMounted(load)
```

Polling делается через `setInterval` + `clearInterval` в `onUnmounted`. Это надёжно, но при многих параллельных полингах будет race conditions.

## 5.7 Self-check

- Что произойдёт, если открыть `/dashboard` без токена? (auth middleware → /login)
- Где хранится текущий пользователь и как обновить его данные везде сразу?
- Как фронт узнаёт, что генерация видео завершилась? (long-polling каждые 3с до `status=='SUCCESS'` или `status=='processing'` пропадёт у lesson)

---

# 6. Инфраструктура и деплой

## 6.1 Сервисы в docker-compose

```
postgres        → бд (volume postgres_data)
redis           → брокер Celery + result backend (с паролем из REDIS_PASSWORD)
silero-tts      → внешний образ navatusein/silero-tts-service на :9898
backend         → FastAPI :8000 (build ./backend)
celery_worker   → тот же образ, команда celery -A app.celery_app worker --pool=prefork -c 2
frontend        → Nuxt :3000 (build ./frontend)
```

Все в сети `edu-network` (bridge). Между собой ходят по DNS-именам: `backend → postgres`, `celery_worker → silero-tts:9898`, и т.д.

Bind-mounts (важно для dev):
- `./backend/app:/app/app` — hot-reload Python кода (uvicorn --reload).
- `./backend/storage:/app/storage` — файлы переживают пересборку.
- `./frontend/src:/app/src` + `./frontend/.nuxt` + `./frontend/node_modules` — нужно для VS Code на хосте, чтобы видеть типы.

## 6.2 Build-process backend

Dockerfile делает много нетривиальных вещей:
1. Меняет Debian-зеркало на `mirror.yandex.ru` (Fastly CDN рвёт коннекты на больших пакетах с RU).
2. Устанавливает **LibreOffice + полный набор шрифтов** (Liberation, DejaVu, Noto, Carlito/Caladea как замена Calibri/Cambria, Microsoft Core Fonts).
3. `fc-cache -fv` дважды — обновляет шрифтовый кеш.
4. Создаёт системного `appuser` (uid=1000) — Celery worker запускается под ним для безопасности.
5. Pip-install через cache mount.
6. Копирует `lo-emoji-substitution.xcu` в корень — этот файл подмешивается в LibreOffice profile при каждом запуске (см. `services/video_service.py:_seed_lo_profile`).

## 6.3 Build-process frontend

1. `node:22-alpine`.
2. `npm install` → копирует `node_modules` в `/opt/node_modules_baked`.
3. `docker-entrypoint.sh` при первом старте сидит bind-mount из этого снепшота, чтобы VS Code на хосте получил реальные `node_modules`.
4. CMD: `nuxt dev --host 0.0.0.0 --no-fork`.

## 6.4 Env-variables (полный список)

| Переменная | Дефолт | Зачем |
|---|---|---|
| `POSTGRES_USER/PASSWORD/DB` | edu_user/edu_password/edu_platform | креды БД |
| `DATABASE_URL` | `postgresql+asyncpg://edu_user:...@postgres:5432/edu_platform` | async строка для FastAPI; в Celery конвертится в psycopg2 |
| `REDIS_PASSWORD` | change-me | пароль Redis |
| `REDIS_URL` | `redis://:change-me@redis:6379/0` | broker+backend Celery |
| `SECRET_KEY` | change-me | подпись JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | срок access |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | срок refresh |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI-совместимый LLM |
| `LLM_MODEL` | qwen3:8b | имя модели |
| `LLM_API_KEY` | ollama | для Ollama любая строка |
| `LLM_TEMPERATURE / LLM_MAX_TOKENS` | 0.7 / 2048 | дефолты для генерации |
| `VISION_PROVIDER` | ollama (или yandex) | какой vision-провайдер |
| `VISION_MODEL` | qwen2.5vl:7b | имя vision-модели |
| `VISION_OLLAMA_BASE_URL / VISION_API_KEY` | host.docker.internal / ollama | для Ollama |
| `YANDEX_VISION_MODEL / FOLDER_ID / API_KEY` | yandexgpt-pro / / | для YandexGPT Vision (production) |
| `TTS_PROVIDER` | silero | пока поддерживается только silero |
| `SILERO_TTS_URL` | http://silero-tts:9898 | endpoint TTS-сервиса |
| `SILERO_TTS_VOICE` | xenia | дефолтный голос |
| `STORAGE_PATH` | /app/storage | путь хранилища внутри контейнера |
| `BASE_URL` | http://localhost:8000 | публичный URL backend (для генерации video_url) |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | разрешённые origins; принимает JSON-массив или CSV |

## 6.5 Поднять локально — пошагово

### Что нужно установить заранее

- **Docker Desktop** (Win/Mac) или Docker + Compose (Linux).
- **Ollama** + модели (если используешь локальный LLM):
  ```bash
  # установка: https://ollama.com/download
  ollama pull qwen3:8b
  ollama pull qwen2.5vl:7b
  ```
- ~30GB свободного места (LibreOffice образ + модели Silero + Ollama).

### Шаги

```bash
# 1. Клонировать
git clone <repo> && cd edu-platform

# 2. Скопировать и заполнить .env
cp .env.example .env
# отредактировать SECRET_KEY и REDIS_PASSWORD

# 3. (опционально) убедиться что Ollama запущен
curl http://localhost:11434/api/tags

# 4. Поднять стек
docker-compose up --build

# 5. (только при первом запуске или новой миграции) применить
# обычно не нужно — backend сам прогоняет alembic upgrade head на старте.
# Но если хочешь сгенерить новую:
docker-compose exec backend alembic revision --autogenerate -m "describe change"
docker-compose exec backend alembic upgrade head
```

### Что должно открыться

| URL | Что |
|---|---|
| http://localhost:3000 | фронт |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | `{"status":"ok"}` |
| http://localhost:8000/files/pptx/... | прямой доступ к файлам |
| http://localhost:9898 | Silero TTS UI |
| http://localhost:5432 | Postgres (можно подключиться через TablePlus) |

### Первый сценарий «end-to-end»

1. Открыть http://localhost:3000 → Зарегистрироваться (роль = teacher).
2. Создать курс → создать модуль → создать урок.
3. На странице урока: выбрать «Презентация + Текст».
4. Загрузить PPTX, ввести 2-3 абзаца текста.
5. Выбрать голос → «Создать видео».
6. Подождать 1–5 минут, наблюдая прогресс по этапам.
7. Получить MP4 в плеере.

Если что-то падает — открыть логи: `docker-compose logs -f backend celery_worker`.

## 6.6 Production-deployment — чего не хватает

> Сейчас проект **MVP**, на прод вытащить «как есть» нельзя. Вот что нужно:

| Проблема | Что сделать |
|---|---|
| Storage локальный | вынести в S3 / Yandex Object Storage; storage_service уже абстрагирован — добавить S3-бекенд |
| `--reload` в backend | в production-комманде убрать; добавить `--workers N` |
| `nuxt dev` во фронте | использовать `nuxt build && node .output/server/index.mjs`; раздавать через nginx |
| `/files/*` через FastAPI | вынести на nginx (X-Accel-Redirect или прямая раздача) |
| Нет HTTPS | terminate в nginx / cloud LB |
| JWT в localStorage | мигрировать на httpOnly+Secure cookie + CSRF |
| Refresh-флоу не работает | добавить interceptor в `useApi` |
| Нет CI/CD | GitHub Actions: lint → tests → docker build → push → deploy |
| Backend lifespan делает migrate | в проде — отдельная миграционная задача (kubectl Job) |
| SECRET_KEY в .env | вынести в secret manager (Vault, AWS SM) |
| Нет мониторинга | Sentry для errors, Prometheus для метрик |

## 6.7 Self-check

- Где должен находиться `lo-emoji-substitution.xcu` чтобы LibreOffice его подхватил?
- Можно ли сменить TTS-провайдера без правки docker-compose? (Ответ: нет — `silero-tts` сервис захардкожен в compose; можно отключить в .env через `TTS_PROVIDER=yandex`, но контейнер всё равно поднимется)
- Куда смотреть, если генерация падает с «No slides produced»?

---

# 7. Technical Debt и слабые места

## 7.1 Безопасность

| Проблема | Файл | Почему опасно | Как исправить |
|---|---|---|---|
| **CORS `allow_credentials=True`** + `allow_origins=["*"]` логически конфликтуют, защита есть в `main.py` | `main.py:82-93` | если кто-то выставит `*` — credentials отключатся (это правильно, но конфигурация тонкая) | задокументировать |

## 7.2 Производительность и масштабирование

| Проблема | Где | Что произойдёт |
|---|---|---|
| **Ollama локально + qwen2.5vl:7b** | `vision_analysis.py` | ~30-60 секунд на слайд; на презентации из 30 слайдов — 15-30 минут |
| **LibreOffice — единственный конвертер** | `video_service.py` | падает на нестандартных шрифтах, эмодзи, сложных анимациях |
| **`silero-tts` HTTP** не имеет очереди | внешний сервис | при 4 параллельных запросах он сам очередит; >10 — может вернуть 500 |
| **Два thread-pool в Celery (4 + 3) на каждом таске** | `tasks/video_pipeline.py:217` | 7 потоков × 2 prefork worker = до 14 потоков → CPU contention с LibreOffice |
| **Storage локальный** | везде | один backend контейнер = single-point-of-failure для файлов |

## 7.3 Корректность

| Проблема | Симптом |
|---|---|

## 7.4 DX и поддерживаемость

- **Нет линтера/форматтера в CI** (хотя `pyrightconfig.json` есть).
- **Нет CONTRIBUTING.md** и единого стиля комментариев.
- **`pages/lessons/[id].vue` — 640 строк** — пора декомпозировать.
- **Дублируется `_get_owned_lesson`** в `routers/lessons.py` и `routers/slides.py` — копипаста.
- **`utils/slide_renderer.py` дублирует логику из `services/video_service.py:convert_pptx_to_images`** — два пайплайна делают одно и то же. Один из них мёртвый код.
- **Магические числа без констант:** `_SILERO_MAX_CHARS = 800`, `MAX_SCRIPT_BYTES`, `_SLIDE_DPI = 150`. Хорошо, что вынесены, плохо — раскиданы по разным файлам.

---

# 8. Engineering Knowledge Transfer

## 8.1 Что обязательно понять с первой недели

### Самое критичное

1. **Два движка БД (async для web, sync для celery).** Если попробуешь использовать `AsyncSession` в Celery-задаче — словишь runtime errors. Если `Session` в FastAPI — заблокируешь event loop.

2. **Celery workers НЕ имеют доступа к FastAPI `app`.** Они импортируют `app.celery_app` независимо. Любой shared state нужно либо в Redis/Postgres, либо в файлах.

3. **`alembic upgrade head` запускается автоматически на старте.** Это значит: коммит с новой миграцией, которую забыли autogenerate'ить → backend не стартует.

4. **CORS-порядок в `main.py` — он критичен и задокументирован комментарием.** Не переставляй middleware местами.

5. **`models/__init__.py` должен реэкспортировать каждую новую модель** — иначе alembic её не увидит.

6. **Storage локальный, не S3.** Если упал backend-контейнер с volume-rebuild → потеряли все курсы.

### Часто забывают

- Frontend кэширует токены в `localStorage` — после смены `SECRET_KEY` пользователи получают 401 пока сами не нажмут logout.
- `task_id` хранится в БД (`analyze_task_id`, `video_task_id`) — это нужно для restore-flow polling после refresh.
- `creation_mode` определяет, какие шаги пайплайна запускаются. Особенно — пропуск VLM-summary в auto-режиме.
- Vision LLM (Ollama qwen2.5vl) **должен быть скачан вручную** на хост перед стартом — Docker не скачает.

## 8.2 Hidden complexity

| Где | Почему сложно |
|---|---|
| **`tasks/video_pipeline.py:217-251`** | два thread-pool в одном `with` блоке, цепочка tts → enc через `as_completed` — нетривиальный concurrent code |
| **`services/llm_service.py:_SSML_SYSTEM`** | очень длинный prompt с конкретными правилами; изменения ломают качество |
| **`services/video_service.py:_trim_trailing_silence`** | без обрезки тишины склейка слайдов выглядит «дёргано» — паузы в конце TTS-аудио |
| **`services/vision_analysis.py:summarize_presentation` + кеш** | кеш-ключ зависит от sha256 PNG + provider + model; смена модели = инвалидация |
| **`main.py: log_and_catch` middleware** | существует ровно для того, чтобы 500-ошибки не теряли CORS-заголовки; убрать = непонятные «CORS» ошибки в браузере |
| **`alembic/versions/48e116fabc1d_init.py:_has_table`** | idempotent миграции — старые БД, бутстрапнутые через `metadata.create_all`, не падают на init |
| **`backend/Dockerfile`** | замена зеркала Debian, отдельный font-cache, msttcorefonts с `\|\| true` (license prompt) |

## 8.3 Неочевидные зависимости

- **LibreOffice-профайл создаётся на каждый запуск** в `_lo_profile/` рядом со слайдами. Если этого не делать — будут гонки за `~/.config/libreoffice`.
- **`silero-tts` качает модель при первом старте** в volume `silero_models`. Первый старт может занять 5+ минут.
- **`host.docker.internal:11434`** — это адрес Ollama, запущенного **на хосте**. На Linux нужен `extra_hosts` или поднятие Ollama в контейнере.
- **Frontend zависит от `~/.nuxt` bind-mount** — без него VS Code на хосте не увидит auto-import типы.
- **`celery_worker` запускается под uid=1000** — все файлы в `storage/` должны быть владельцами этого uid, иначе permission denied.

## 8.4 Важные architectural decisions (с обоснованием)

| Решение | Альтернатива | Почему выбрано |
|---|---|---|
| Celery + Redis вместо ARQ / Dramatiq | ARQ нативно async | Celery доминирует в экосистеме, тонна docs, prefork даёт изоляцию падений |
| Двойной DB-driver | Использовать только async + `asgiref.sync_to_async` | overhead не оправдан; sync проще для CPU-bound CV/CPU-задач |
| LibreOffice вместо python-pptx-rendering | python-pptx умеет читать XML, но не рендерить | надёжно сохраняет шрифты, эмодзи, картинки |
| Vision LLM вместо OCR | tesseract / paddleocr | LLM понимает контекст и пишет связный текст, а не просто извлекает символы |
| Nuxt SSR off (SPA) | Полный SSR | проще деплой (статика); SEO для лендинга не критичен |
| `useState` вместо Pinia | Pinia | проект пока маленький |
| Локальное хранилище | S3 сразу | MVP-скорость; миграция готова — через `storage_service` |
| FastAPI отдаёт статику | Сразу nginx | dev-удобство; в проде надо переключить |
| Прохождение alembic в lifespan | Отдельная команда | гарантирует, что код и схема синхронны на каждом старте |

---

# 9. Learning Path (Roadmap изучения)

## 9.1 День 1 — High level

1. Прочитать `README.md` и разделы 1-3 этого документа.
2. Запустить проект локально (раздел 6.5).
3. Пройти end-to-end сценарий: зарегистрироваться teacher-ом, загрузить простой PPTX, сгенерировать видео.
4. Открыть Swagger `/docs` и поэкспериментировать с API.

**Цель:** увидеть продукт глазами пользователя.

## 9.2 День 2 — Backend core

В таком порядке:
1. [backend/app/main.py](backend/app/main.py) — точка входа.
2. [backend/app/config.py](backend/app/config.py) и [backend/app/database.py](backend/app/database.py) — основа.
3. [backend/app/dependencies.py](backend/app/dependencies.py) — паттерн auth.
4. Все [models/](backend/app/models/) — понять схему БД (чертёж в разделе 4.1).
5. Все [schemas/](backend/app/schemas/) — формат API.
6. [routers/auth.py](backend/app/routers/auth.py) — самый простой router, понять паттерн.
7. [routers/courses.py](backend/app/routers/courses.py) → [lessons.py](backend/app/routers/lessons.py) → [students.py](backend/app/routers/students.py).

**Цель:** понимать, что делает каждый эндпоинт без запуска сервера.

## 9.3 День 3 — Сервисы и пайплайн

1. [services/auth_service.py](backend/app/services/auth_service.py) — самый короткий.
2. [services/storage_service.py](backend/app/services/storage_service.py) — обёртка над файлами.
3. [services/llm_service.py](backend/app/services/llm_service.py) — внимательно прочитать prompts.
4. [services/tts_service.py](backend/app/services/tts_service.py) — обёртка над Silero.
5. [services/video_service.py](backend/app/services/video_service.py) — самый сложный (FFmpeg + LibreOffice).
6. [services/vision_analysis.py](backend/app/services/vision_analysis.py).
7. [tasks/video_pipeline.py](backend/app/tasks/video_pipeline.py) — read very carefully, это сердце системы.
8. [tasks/vision_pipeline.py](backend/app/tasks/vision_pipeline.py).

**Цель:** уметь объяснить пайплайн от PPTX до MP4 устно.

## 9.4 День 4 — Frontend

1. [frontend/nuxt.config.ts](frontend/nuxt.config.ts) и [package.json](frontend/package.json).
2. [src/composables/useApi.ts](frontend/src/composables/useApi.ts), [useAuth.ts](frontend/src/composables/useAuth.ts), [useCreationMode.ts](frontend/src/composables/useCreationMode.ts).
3. [src/middleware/](frontend/src/middleware/).
4. [src/components/UiButton.vue](frontend/src/components/UiButton.vue) — пример паттерна компонента.
5. [src/pages/login.vue](frontend/src/pages/login.vue) и [register.vue](frontend/src/pages/register.vue).
6. [src/pages/dashboard.vue](frontend/src/pages/dashboard.vue) → [courses/[id].vue](frontend/src/pages/courses/[id].vue).
7. [src/pages/lessons/[id].vue](frontend/src/pages/lessons/[id].vue) — самый сложный, читать с готовым beklimentom.
8. [src/components/SlideTextEditor.vue](frontend/src/components/SlideTextEditor.vue).
9. [src/components/PipelineStages.vue](frontend/src/components/PipelineStages.vue).
10. Студенческая часть: [pages/student/](frontend/src/pages/student/) и [components/LessonPlayer.vue](frontend/src/components/LessonPlayer.vue).

**Цель:** понимать, как UI-события превращаются в API-вызовы.

## 9.5 День 5 — Инфра и долг

1. Backend Dockerfile и frontend Dockerfile.
2. docker-compose.yml.
3. Все миграции в порядке создания.
4. Раздел 7 этого документа — список технического долга. Прочитать вдумчиво.
5. Запустить `docker-compose logs -f` и посмотреть, как взаимодействуют сервисы при генерации одного видео.

## 9.6 Что можно временно игнорировать

- `silero/config.py` — это конфиг **внешнего контейнера**, в проекте не используется напрямую.
- `backend/app/.stubs/` — заглушки для type-checker'а.
- `backend/app/utils/slide_renderer.py` — параллельная (мёртвая?) реализация PPTX→PNG; в боевом пайплайне не вызывается.
- `frontend/src/components/UiInput.vue` — UI-кит, простой компонент.
- `frontend/.nuxt/` — генерируется автоматически.

## 9.7 Самые важные файлы (top-10)

1. **[backend/app/tasks/video_pipeline.py](backend/app/tasks/video_pipeline.py)** — сердце.
2. **[backend/app/main.py](backend/app/main.py)** — точка входа.
3. **[backend/app/services/video_service.py](backend/app/services/video_service.py)** — сложная FFmpeg-логика.
4. **[backend/app/services/llm_service.py](backend/app/services/llm_service.py)** — все LLM prompts.
5. **[backend/app/services/vision_analysis.py](backend/app/services/vision_analysis.py)** — vision-логика.
6. **[backend/app/models/lesson.py](backend/app/models/lesson.py)** — самая нагруженная сущность.
7. **[backend/app/dependencies.py](backend/app/dependencies.py)** — auth-паттерн.
8. **[frontend/src/pages/lessons/[id].vue](frontend/src/pages/lessons/[id].vue)** — главная UX-страница.
9. **[frontend/src/components/SlideTextEditor.vue](frontend/src/components/SlideTextEditor.vue)** — самая сложная UI.
10. **[docker-compose.yml](docker-compose.yml)** — операционная карта.

---

# 10. Final Knowledge Test

## 10.1 Теория (20 вопросов)

1. Объясни разницу между `presentation_and_text` и `presentation_auto`. Какие шаги пайплайна различаются?
2. Где именно в коде делается `alembic upgrade head` при старте FastAPI? Зачем это сделано?
3. Почему backend и Celery worker используют разные DB-движки? Что произойдёт, если в Celery написать `await db.commit()` через AsyncSession?
4. Сколько уровней middleware у FastAPI и в каком порядке они выполняются? В каком из них живёт `log_and_catch`?
5. Какой API-эндпоинт можно вызвать без авторизации, но нельзя без знания access-кода?
6. Какова цель `analyze_task_id` и `video_task_id` в таблице `lessons`?
7. Что такое SSML и зачем он используется в `llm_service.split_and_annotate_ssml`?
8. Опиши формат кеш-ключа для PPTX-конвертации. Где он формируется и как инвалидируется?
9. Как фронтенд узнаёт, что нужно показать `SlideTextEditor` вместо обычной формы?
10. Какая модель Pydantic используется для тела `POST /api/v1/lessons/{id}/generate-video`? Какие поля и валидаторы?
11. Почему в `auth_service.hash_password` пароль сначала прогоняется через SHA-256, а потом через bcrypt? Какая уязвимость это создаёт?
12. Как реализовано «поминутное» обновление состояния задачи в Celery? (Подсказка: `update_state(state="PROGRESS", ...)`.)
13. Что произойдёт при удалении пользователя? Какие записи каскадно удалятся?
14. Опиши, как работает `_trim_trailing_silence` и зачем он нужен в пайплайне.
15. В чём отличие `analyze_presentation` от `summarize_presentation` в `vision_analysis_service`? Почему первая последовательная, а вторая параллельная?
16. Какой компонент во фронтенде использует **глобальный** state? Как этот state создаётся?
17. Что делает `ProgressBar` со значением `value > total`? (Прочитай код.)
18. Какой максимальный размер файла принимает `/uploads/script` и почему?
19. Почему `bare.vue` layout используется на лендинге?
20. Где в проекте нарушено правило DRY (один и тот же код в двух местах)?

## 10.2 Сценарии «что произойдёт если...»

21. **Что произойдёт, если убить Celery worker во время генерации видео?**
   *Ответ: задача останется в статусе STARTED в Redis; lesson останется в статусе `processing`; задача перезапустится при перезапуске worker'а только если есть `acks_late=True` (его нет — значит задача потеряется). Файлы в `work_dir` останутся (finally не выполнится). Пользователь увидит вечный «processing» и сможет только нажать «перегенерировать».*

22. **Что произойдёт, если изменить `SECRET_KEY` в .env и перезапустить backend?**
   *Все существующие access/refresh токены станут невалидными. Все залогиненные юзеры получат 401 при следующем запросе. Frontend очистит localStorage и редиректнёт на /login.*

23. **Что произойдёт, если удалить файл из `storage/pptx/<uuid>_file.pptx`, но `lesson.pptx_path` остался?**
   *Следующий `generate-video` упадёт на `convert_pptx_to_images` с RuntimeError. lesson получит status=`error`. Существующее видео (если было) продолжит работать.*

24. **Что произойдёт, если LLM вернёт 11 SSML-чанков для 10 слайдов?**
   *`split_and_annotate_ssml` сравнит длину с `slides_count`, увидит несоответствие, залогирует warning и вызовет `_fallback_ssml` — простое разбиение по предложениям.*

25. **Что произойдёт, если два преподавателя сгенерируют видео для лекций с одинаковым PPTX-файлом одновременно?**
   *Кеш PPTX→PNG одинаковый по содержимому, оба попадут в одну `cached_dir`. Поскольку это директория с PNG-файлами и оба процесса их пишут одинаковыми именами — race condition возможен, но в худшем случае один процесс перезапишет PNG другого тем же содержимым. Безопасно, но грязно.*

26. **Что произойдёт, если Ollama-сервер выключен?**
   *`split_and_annotate_ssml` упадёт с connection error → except перехватит → `_fallback_ssml`. Видео сгенерируется, но качество скрипта упадёт. Если выключен и при vision-анализе — pipeline упадёт с error, пользователь увидит «Vision LLM returned no text...».*

27. **Что произойдёт, если в БД создать `Course` без `owner`?**
   *Не создашь: `owner_id NOT NULL`. SQLAlchemy/Postgres вернёт IntegrityError.*

28. **Что произойдёт, если сменить роль пользователя с teacher на student в БД напрямую?**
   *Старые JWT-токены содержат `role` в payload, но `dependencies.require_teacher` проверяет роль из БД (`user.role`). Поэтому смена сработает мгновенно после следующего запроса.*

## 10.3 Дебаг-сценарии

29. **Пользователь говорит «нажал «создать видео», крутится 20 минут, ничего не происходит». Куда смотреть?**
   - `docker-compose logs celery_worker` — есть ли вообще задача?
   - `lesson.video_task_id` в БД → `AsyncResult(task_id).status` — какой статус?
   - PROGRESS-meta — на каком шаге застряли? Если на `tts` — проверить `silero-tts` (curl `:9898`). Если на `llm` — проверить ollama. Если на `slides` — LibreOffice / диск.
   - `docker stats` — может, кончилась память?

30. **Фронт стабильно показывает «CORS error» на любом запросе. Что проверить?**
   - `CORS_ORIGINS` в `.env` — содержит ли `http://localhost:3000`?
   - Backend живой? Не падает ли он на 500-ке? (См. раздел 1.4 main.py — без `log_and_catch` middleware 500 возвращалась бы без CORS-заголовков, и браузер показывал бы это как CORS-ошибку.)
   - Был ли pre-flight OPTIONS-запрос? В Network tab.

31. **`generate-video` возвращает 200, но статус урока не меняется. Куда смотреть?**
   - Запущен ли `celery_worker`? `docker-compose ps` → State.
   - Подключился ли он к Redis? `docker-compose logs celery_worker` ищем `Connected to redis://...`.
   - Включена ли в `celery_app.include` нужная задача? (`app.tasks.video_pipeline`).

## 10.4 Практические задачи

32. **Добавить новый эндпоинт** `GET /api/v1/courses/{id}/stats`, возвращающий `{enrollments_count, lessons_count, completed_lessons_count}`. Где создать handler? Какие модели использовать? Какую схему ответа?

33. **Добавить миграцию**: новое поле `Course.is_premium: bool default False`. Что выполнить?

34. **Добавить нового LLM-провайдера** (например, Anthropic Claude). Какие файлы изменить? Сколько мест в коде?

35. **Заменить локальный storage на S3.** Какие файлы переписать? Что нужно сохранить совместимым?

36. **Добавить тест на регистрацию пользователя.** Как настроить тестовую БД? Какой клиент использовать?

37. **Уменьшить время генерации видео в 2 раза.** Какие места узкие? Что можно распараллелить ещё? (Идеи: pre-render слайдов сразу после загрузки PPTX, кеш TTS по hash текста, более мелкие чанки для encode_segment.)

38. **Реализовать рабочий refresh-флоу на фронте.** Где править `useApi.ts`? Какие edge-cases (одновременные запросы при просроченном токене)?

---

# Заключение

Этот гайд покрывает MVP-состояние проекта на момент написания. Он намеренно показывает не только «как сделано», но и **что плохо** и **почему**. Это не попытка обидеть авторов кода — это часть профессионального онбординга: новый человек должен видеть и сильные, и слабые стороны системы, иначе будет копировать антипаттерны.

После того как ты прочитал и понял всё выше:
- ты знаешь, **где жить** в коде для каждой типовой задачи;
- ты знаешь, **что не трогать** без особой нужды;
- у тебя есть **ментальная модель** всей системы — от клика пользователя до MP4 на диске;
- ты можешь **отлаживать** падения, а не только разбираться по симптомам;
- ты понимаешь **trade-offs** каждого крупного решения и можешь их обсуждать с командой.

Удачи. Если что — `docker-compose logs -f` твой лучший друг.
