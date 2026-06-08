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
| **OpenAI SDK** | универсальный клиент к LLM. Ollama и YandexGPT эмулируют OpenAI API → один и тот же код работает для обоих провайдеров. |
| **Silero TTS** | бесплатный OSS-TTS для русского. Запускается отдельным docker-контейнером (`navatusein/silero-tts-service`) и общается по HTTP. |
| **LibreOffice headless** | единственный надёжный способ конвертировать PPTX в PDF без потери шрифтов и эмодзи. Альтернатив на Python нет. |
| **FFmpeg + poppler (pdftoppm)** | индустриальный стандарт для рендеринга PDF в PNG и склейки кадров с аудио в MP4. |

### Frontend — Node 22 / TypeScript

| Технология | Зачем |
|---|---|
| **Nuxt 3.14 (SPA)** | Vue + готовый file-based routing + auto-imports + composables. SSR отключён (`ssr: false`) — приложение работает как чистая SPA, что упрощает деплой (статика). |
| **Vue 3.5** | реактивность, простой шаблонный синтаксис. |
| **Tailwind CSS 3.4** | utility-first CSS — UI пишется быстро без отдельных `.css` файлов. |
| **lucide-vue-next** | современная библиотека SVG-иконок. |

| **Pinia 2** | канонический слой состояния. Сторы: `auth`, `billing`, `comments`, `student` (`frontend/src/stores/`). |

**State теперь на Pinia, а не на `useState`.** Раньше глобальное состояние держали в `useState('key', factory)` — сейчас канонический слой это **Pinia** (`useAuthStore` и др.). `composables/useCreationMode.ts` — это *не* стор, а модуль констант. Новое shared-состояние добавляем стором, а не `useState`-синглтоном.

### Инфраструктура

- **docker-compose** с шестью сервисами (см. секцию 4).
- Внешняя зависимость на хосте: **Ollama** с двумя моделями (`qwen3:8b` для текста, `qwen2.5vl:7b` для vision). Контейнер backend обращается к ним через `host.docker.internal:11434`.
- Локальное файловое хранилище в `backend/storage/` (volume), раздаётся через FastAPI `StaticFiles` на префиксе `/files/*`.

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
│                · gradebook · analytics · billing · files        │
│   services:    auth · llm · tts · storage · video · vision ·    │
│                quiz · grading · gradebook · comment · billing · │
│                email · email_token · signed_url · analytics     │
│   tasks (Celery): video · vision · quiz · email · purge          │
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
       sync engine    │   • Ollama LLM  (split + SSML)          │
       (psycopg2)     │   • Ollama Vision (slide → narration)   │
                      │   • Silero TTS HTTP :9898               │
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
| `silero-tts` | navatusein/silero-tts-service | 9898 | внешний TTS-сервис, отдельный контейнер |
| `backend` | (build ./backend) | 8000 | FastAPI с uvicorn `--reload` |
| `celery_video` | образ backend | — | queue `video`, `-c 2` — PPTX→MP4 пайплайн |
| `celery_vision` | образ backend | — | queue `vision`, `-c 1` — vision-LLM анализ слайдов |
| `celery_quiz` | образ backend | — | queue `quiz`, `-c 2`, **`--beat`** — генерация/проверка тестов + суточный `purge_soft_deleted` |
| `celery_email_worker` | образ backend | — | queue `celery_email`, `-c 2` — транзакционные письма |
| `prometheus` | prom/prometheus | 9090 | сбор метрик с backend |
| `grafana` | grafana/grafana | 3001 | дашборды поверх Prometheus |
| `flower` | образ backend | 5555 | мониторинг Celery (basic-auth) |
| `frontend` | (build ./frontend) | 3000 | Nuxt dev server (`nuxt dev --host 0.0.0.0`) |

Все в общей сети `edu-network` — общаются по DNS-именам контейнеров (`backend → postgres:5432`, `celery_video → silero-tts:9898`, и т.д.).

> **Важно про очереди:** каждый воркер слушает свою очередь (`--queues=…`). Новая Celery-задача
> попадёт к воркеру, только если её зароутить в правильную очередь — иначе её никто не возьмёт.
> **Beat-планировщик** встроен ровно в один воркер (`celery_quiz --beat`); в кластере он должен быть
> единственным. См. [DECISIONS.md](DECISIONS.md) и [docker-compose.yml](../docker-compose.yml).

---

## 5. Основные модули backend в деталях

```
backend/app/
├── main.py            ← точка входа (FastAPI app, middleware, lifespan)
├── config.py          ← pydantic-settings, читает .env
├── database.py        ← async engine, get_db, Base
├── dependencies.py    ← get_current_user, require_teacher, require_student
├── celery_app.py      ← инстанс Celery (broker=Redis)
├── models/            ← SQLAlchemy ORM (один файл = одна доменная сущность)
├── schemas/           ← Pydantic DTO (вход/выход API)
├── routers/           ← HTTP endpoints, по одному файлу на ресурс
├── services/          ← переиспользуемая бизнес-логика
├── tasks/             ← Celery-задачи (PPTX→MP4 пайплайн)
└── utils/             ← вспомогательные модули
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
├── app.vue                  ← <NuxtLayout><NuxtPage/></NuxtLayout>
├── layouts/
│   ├── default.vue          ← AppHeader + контейнер
│   └── bare.vue             ← без header (лендинг, dashboard)
├── stores/                  ← Pinia (канонический state)
│   ├── auth.ts              ← useAuthStore: user/isAuthenticated/login/logout
│   ├── billing.ts · comments.ts · student.ts
├── middleware/
│   ├── auth.ts              ← opt-in на странице: редирект на /login (не глобальный)
│   ├── guest.ts             ← уводит залогиненных с /login,/register
│   └── teacher.ts           ← студентов отправляет в /student/dashboard
├── composables/
│   ├── useApi.ts            ← API-клиент: cookie-auth (credentials:include),
│   │                          double-submit CSRF, реактивный refresh на 401
│   ├── useProgressStream.ts ← SSE-подписка на прогресс Celery-задачи
│   ├── useAiGuard.ts        ← открывает «подтвердите email» на AI-действиях
│   └── useCreationMode.ts   ← режимы создания урока (модуль констант, не стор)
├── pages/                   ← file-based routing
│   ├── index.vue            ← лендинг
│   ├── login.vue / register.vue
│   ├── dashboard.vue        ← teacher: список курсов
│   ├── courses/
│   │   ├── create.vue
│   │   └── [id].vue         ← модули + уроки + публикация
│   ├── lessons/
│   │   └── [id].vue         ★ главная рабочая страница (640 строк)
│   └── student/
│       ├── dashboard.vue
│       └── courses/[id].vue ← плеер уроков
└── components/
    ├── SlideTextEditor.vue  ★ редактор текстов слайдов (320 строк)
    ├── PipelineStages.vue   ← stepper прогресса
    ├── CreationModeChooser.vue
    ├── CourseCard.vue / SkeletonCard.vue / StatusBadge.vue
    ├── AppHeader.vue / AppSidebar.vue / LessonPlayer.vue
    └── UiButton.vue / UiInput.vue
```

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

### 8.2 Локальное файловое хранилище вместо S3
- **Решение:** всё (PPTX, PNG слайдов, MP4) лежит в `backend/storage/` volume.
- **Почему:** MVP-скорость. `storage_service` уже абстрагирован, чтобы при необходимости подменить бекенд на S3.
- **Trade-off:** не масштабируется на горизонталь (несколько backend-инстансов не увидят файлов друг друга), нет CDN, потеря контейнера = потеря всего контента.

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
- **Решение:** в `tasks/video_pipeline.py` параллельно работают `tts_pool` (4 потока, по запросу к Silero) и `enc_pool` (3 потока, по FFmpeg-процессу). Цепочка: как только TTS слайда K готов, тут же стартует encoding K, не дожидаясь TTS остальных.
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

### 8.11 Auto-applied миграции в `lifespan`
- **Решение:** `app/main.py:_ensure_schema_at_head` запускает `alembic upgrade head` на старте.
- **Почему:** в dev-режиме это удобно — перезапустил контейнер, схема актуальна. Заменяет старый «бутстрап через `Base.metadata.create_all`», который рассинхронизировался с историей миграций.
- **Trade-off:** в проде так делать опасно (миграция может быть тяжёлой и должна быть отдельным шагом деплоя). Для прода нужно вынести в `kubectl Job` или CI-step.

---

## 9. Что обязательно понять с первой недели

1. **Async вне Celery, sync внутри Celery.** Не путай.
2. **`models/__init__.py` должен реэкспортировать новые модели**, иначе alembic не увидит.
3. **`alembic upgrade head` запускается автоматически** на старте — забыл сгенерировать миграцию = backend не стартует.
4. **`task_id` хранится в БД** (`analyze_task_id`, `video_task_id`), чтобы фронт мог продолжить poll'ить после refresh страницы.
5. **`creation_mode` определяет шаги пайплайна** — особенно пропуск VLM-summary в auto-режиме.
6. **Vision-LLM качается вручную** на хост: `ollama pull qwen2.5vl:7b`.
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
| **Комментарии** | `models/comment.py`, `services/comment_service.py`, `routers/comments.py` | Треды комментариев к урокам. |
| **Журнал оценок / аналитика** | `services/gradebook_service.py`, `analytics_service.py`, `routers/gradebook.py`, `analytics.py` | Сводки по курсу/уроку, ручные override оценок, аналитика по квизам. |
| **S3-бэкенд хранилища** | `services/storage_service.py`, `signed_url_service.py`, `config.py` (`STORAGE_BACKEND`) | Хранилище переключается `local`↔`s3` (Yandex Object Storage/совместимое). При `local` отдаётся через `/files/*` с HMAC-подписанными URL; `files`-роутер регистрируется только в `local`-режиме. |
| **Наблюдаемость** | `main.py`, `celery_app.py`, `logging_config.py`, `monitoring/` | Sentry (FastAPI+Celery+SQLAlchemy), Prometheus-метрики (HTTP + Celery-сигналы) → Grafana, Flower для Celery, structlog с `request_id`. |

---

## 10. Что читать дальше

- [DATA_FLOW.md](DATA_FLOW.md) — пошаговые сценарии для каждого ключевого UX.
- [AUTH_FLOW.md](AUTH_FLOW.md) — JWT, роли, как обрабатывается истечение токена.
- [DEPLOYMENT.md](DEPLOYMENT.md) — как поднять локально с нуля.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — где ходит технический долг.
- [DECISIONS.md](DECISIONS.md) — расширенная аргументация выбранных решений.
