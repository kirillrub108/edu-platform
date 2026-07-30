# DEPLOYMENT — поднятие проекта с нуля

> Только реальные команды, которые работают на текущем коде. Основной фокус — **dev-флоу** (разделы 1–6). Базовый **production-рантайм уже есть** в репозитории — self-contained [docker-compose.prod.yml](../docker-compose.prod.yml) (gunicorn, nginx+TLS, one-shot `migrate`, сайдкар `db_backup`, certbot) + [frontend/Dockerfile.prod](../frontend/Dockerfile.prod); подробности и порядок деплоя — в разделе 7. То, что ещё НЕ реализовано (S3-переезд, secret manager, off-host backup, вынос Ollama), помечено там же.

---

## 1. Системные требования

| Что | Версия | Зачем |
|---|---|---|
| **Docker Desktop** (Win/Mac) или Docker Engine + Compose v2 (Linux) | 24+ | вся инфра поднимается через docker-compose |
| **LLM+vision-провайдер** | — | дефолт `.env.example` — облако **Polza AI** (нужен только API-ключ `pza_...`). Альтернатива — **Ollama на хосте** (см. шаг 3-Б) |
| **Свободного места на диске** | ~10 GB (облако) / ~30 GB (локальный Ollama) | Docker-образы + LibreOffice (~500MB) + модели Silero (~50MB); модели Ollama добавляют 10–15 GB |
| **RAM** | 8+ GB (облако) / 16+ GB (Ollama) | параллельно работают backend, postgres, redis, 4 celery-воркера, frontend; локальный инференс LLM добавляет ~10GB |
| **CPU** | 4+ ядра | пулы TTS/FFmpeg авто-масштабируются от числа ядер (`constants._derive_concurrency`, cap 12) |

GPU не обязателен; актуален только для локального Ollama (vision-анализ ускоряется в 5-10 раз).

---

## 2. Установка с нуля

### Шаг 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd edllm
```

### Шаг 2. Создать `.env` из шаблона

```bash
cp .env.example .env
```

Открыть в редакторе и **обязательно** поменять:

| Переменная | Что положить |
|---|---|
| `SECRET_KEY` | случайную строку 32+ символа (`openssl rand -hex 32`) |
| `REDIS_PASSWORD` | любую строку, синхронно с тем же значением в `REDIS_URL` |
| `POSTGRES_PASSWORD` | любую (для dev можно оставить как есть) |

Полный список переменных — раздел 5 этого файла.

### Шаг 3. Настроить LLM+vision-провайдера

**Вариант А — Polza AI (облако, дефолт `.env.example`).** Ничего ставить не нужно — только
ключ в `.env`:

```
LLM_BASE_URL=https://api.polza.ai/v1
LLM_MODEL=qwen/qwen3-30b-a3b-instruct-2507
LLM_API_KEY=pza_...            # ваш ключ
VISION_OLLAMA_BASE_URL=https://api.polza.ai/v1
VISION_MODEL=qwen/qwen3.6-27b
VISION_API_KEY=pza_...
```

Опционально: `LLM_PROVIDER_ORDER` / `VISION_PROVIDER_ORDER` пинят upstream-провайдера гейтвея
(OpenRouter-стиль), `VISION_REASONING_DISABLED=true` глушит chain-of-thought у reasoning-моделей.

**Вариант Б — Ollama на хосте (локально, бесплатно).**

```bash
# 1. Скачать с https://ollama.com/download → установить.
# 2. Проверить, что демон запущен и слушает 11434:
curl http://localhost:11434/api/tags

# 3. Скачать модели (имена = LLM_MODEL/VISION_MODEL в .env):
ollama pull qwen3:8b       # для текстовых задач (split, SSML)
ollama pull qwen2.5vl:7b   # для vision-анализа слайдов
```

И в `.env`: `LLM_BASE_URL=http://host.docker.internal:11434/v1`, `LLM_MODEL=qwen3:8b`,
`VISION_OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`, `VISION_MODEL=qwen2.5vl:7b`,
ключи — любая строка (`ollama`). Ollama должна остаться запущенной.

> **Linux:** `host.docker.internal` резолвится через `extra_hosts: host-gateway`, который уже
> прописан для сервиса `backend` в [docker-compose.yml](../docker-compose.yml). У celery-воркеров
> его нет — при локальном Ollama на Linux добавь тот же блок воркерам (`celery_vision` ходит в
> vision-LLM, `celery_video`/`celery_quiz` — в текстовый).

### Шаг 4. Поднять весь стек

```bash
docker-compose up --build
```

При первом запуске:
- скачается образ postgres:17-alpine, redis:8-alpine, navatusein/silero-tts-service;
- соберётся `backend` (~5 минут — устанавливаются LibreOffice, шрифты, ffmpeg, poppler);
- соберётся `frontend` (~2 минуты — `npm install`);
- `silero-tts` скачает модель `v5_5_ru.pt` в volume `silero_models` (~1 минута на первый старт);
- `backend` через `lifespan` автоматически прогонит `alembic upgrade head` — схема создастся.

Готово, когда в логах `backend-1` появилось:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Шаг 5. Проверить, что всё работает

| URL | Что должно открыться |
|---|---|
| http://localhost:3000 | Лендинг Nuxt |
| http://localhost:8000/docs | Swagger UI с роутерами |
| http://localhost:8000/health | `{"status":"ok"}` |
| http://localhost:8000/redoc | ReDoc альтернативная документация |
| http://localhost:9898 | Silero TTS UI |

### Шаг 6. Первый сценарий «end-to-end»

1. Открыть http://localhost:3000 → «Создать аккаунт».
2. Зарегистрироваться (роль = teacher по умолчанию).
3. На `/dashboard` → «+ Создать курс».
4. На странице курса → «+ Модуль» → внутри модуля «+ Урок».
5. На странице урока → выбрать карточку «Презентация + Текст».
6. Загрузить PPTX (любой), вставить 2-3 абзаца текста доклада.
7. Выбрать голос → «Создать видео».
8. Подождать 1-5 минут, наблюдая прогресс по этапам (slides → summary → llm → tts → encoding).
9. Получить готовый `<video>`.

Если что-то падает — в раздел 6 «Диагностика».

---

## 3. Команды повседневного использования

### Базовые

```bash
# Запустить всё в режиме live-logs
docker-compose up

# Запустить в фоне
docker-compose up -d

# Остановить (контейнеры удалятся, volumes останутся)
docker-compose down

# Остановить и удалить volumes (потеря БД и storage!)
docker-compose down -v

# Пересобрать только backend (например, после изменения requirements.txt)
docker-compose up --build backend

# Тейлить логи одного сервиса (воркеры: celery_video, celery_vision,
# celery_quiz, celery_email_worker)
docker-compose logs -f --timestamps backend
docker-compose logs -f --timestamps celery_video
```

### Работа с миграциями

```bash
# Сгенерировать миграцию из изменений моделей
docker-compose exec backend alembic revision --autogenerate -m "describe change"

# Применить все миграции
docker-compose exec backend alembic upgrade head

# Откатить на одну миграцию
docker-compose exec backend alembic downgrade -1

# Посмотреть текущую версию
docker-compose exec backend alembic current

# История
docker-compose exec backend alembic history
```

> **Замечание:** `alembic upgrade head` запускается автоматически в `lifespan` при старте backend. Ручной вызов нужен только в неинтерактивных сценариях (например, выполнение в чужом окружении).

### Работа с БД

```bash
# psql shell внутри postgres-контейнера
docker-compose exec postgres psql -U edu_user -d edllm

# Дамп
docker-compose exec postgres pg_dump -U edu_user edllm > dump.sql

# Восстановление
cat dump.sql | docker-compose exec -T postgres psql -U edu_user -d edllm
```

### Работа с Celery

Воркеров четыре — по одному на очередь: `celery_video` (video), `celery_vision` (vision),
`celery_quiz` (quiz, + `--beat`), `celery_email_worker` (celery_email).

```bash
# Перезапустить один воркер (без backend)
docker-compose restart celery_video

# Посмотреть активные задачи (можно на любом воркере)
docker-compose exec celery_quiz celery -A app.celery_app inspect active

# Очистить ВСЁ состояние Redis (очереди, refresh-семейства, чекпоинты пайплайна,
# result backend) — только как крайняя мера в dev:
docker-compose exec redis redis-cli -a "$REDIS_PASSWORD" flushdb
```

### Работа со storage

```bash
# Посмотреть, что лежит
ls -la backend/storage/pptx/
ls -la backend/storage/videos/

# Очистить кеши (безопасно — пересоздадутся)
rm -rf backend/storage/slides_cache backend/storage/summaries_cache

# Очистить временные job-директории (если что-то «застряло»)
rm -rf backend/storage/video_jobs/
```

### Работа с Frontend

```bash
# Пересобрать frontend (после изменения package.json)
docker-compose up --build frontend

# Войти в контейнер для локальной отладки
docker-compose exec frontend sh
```

---

## 4. Запуск backend без Docker (для дебага под отладчиком)

Иногда удобно запустить FastAPI на хосте, оставив postgres/redis/silero в Docker.

```bash
# 1. Поднять только инфраструктуру
docker-compose up -d postgres redis silero-tts

# 2. Установить Python 3.13 и зависимости
cd backend
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate           # Windows PowerShell

pip install -r requirements.txt

# 3. Установить системные зависимости
# Ubuntu/Debian:
sudo apt install libreoffice ffmpeg poppler-utils
# Mac:
brew install libreoffice ffmpeg poppler

# 4. Поправить URLs в env (хост вместо контейнерных DNS)
export DATABASE_URL="postgresql+asyncpg://edu_user:edu_password@localhost:5432/edllm"
export REDIS_URL="redis://:change-me@localhost:6379/0"
export SILERO_TTS_URL="http://localhost:9898"
export LLM_BASE_URL="http://localhost:11434/v1"
export VISION_OLLAMA_BASE_URL="http://localhost:11434/v1"
# и остальные из .env

# 5. Запустить uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Внимание:** в этом режиме Celery worker остаётся в Docker, и его DATABASE_URL внутри контейнера всё ещё указывает на `postgres:5432`. Для полной согласованности нужен compose-override или запуск Celery тоже на хосте.

---

## 5. Полный список переменных окружения

Все живут в `.env` в корне проекта. **Источник истины по дефолтам —
[config.py](../backend/app/config.py)** (pydantic-settings); `.env.example` — шаблон с
рабочими облачными значениями, `.env.prod.example` — прод-надстройка. Ниже — по группам.

### PostgreSQL

| Переменная | Дефолт | Использование |
|---|---|---|
| `POSTGRES_USER` | edu_user | для compose: создаёт пользователя БД |
| `POSTGRES_PASSWORD` | edu_password | пароль |
| `POSTGRES_DB` | edllm | имя БД |
| `DATABASE_URL` | `postgresql+asyncpg://edu_user:edu_password@postgres:5432/edllm` | async строка для FastAPI; в Celery конвертится в `+psycopg2` |

### Redis

| Переменная | Дефолт | Использование |
|---|---|---|
| `REDIS_PASSWORD` | change-me | передаётся в `redis-server --requirepass` |
| `REDIS_URL` | `redis://:change-me@redis:6379/0` | broker + result backend Celery + auth-state + чекпоинты |

> Пароль в `REDIS_URL` должен совпадать с `REDIS_PASSWORD`. Это **отдельные переменные** — рассинхрон вызовет «WRONGPASS» в логах воркеров.

### JWT / cookies

| Переменная | Дефолт (config.py) | Использование |
|---|---|---|
| `SECRET_KEY` | **нет дефолта — обязателен** | подпись JWT (HS256), email-verify-токенов и HMAC `/files/*`. При `ENVIRONMENT=production` слабый/шаблонный ключ (<32 симв.) валит старт |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | срок жизни access |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 14 | sliding-окно refresh при `remember_me` (`.env.example` ставит 120) |
| `REFRESH_TOKEN_SESSION_DAYS` | 1 | sliding-окно без `remember_me` |
| `REFRESH_TOKEN_ABSOLUTE_MAX_DAYS` | 90 | абсолютный потолок семейства (`.env.example` — 365) |
| `COOKIE_SECURE` | false | в проде `true` (HTTPS-only куки) |
| `COOKIE_SAMESITE` | Lax | samesite всех auth-кук |

### LLM (текстовый)

| Переменная | Дефолт (config.py) | `.env.example` | Использование |
|---|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | `https://api.polza.ai/v1` | OpenAI-совместимый endpoint |
| `LLM_MODEL` | qwen3:8b | `qwen/qwen3-30b-a3b-instruct-2507` | имя модели |
| `LLM_API_KEY` | ollama | `pza_...` | ключ провайдера |
| `LLM_TEMPERATURE` | 0.7 | — | для `enhance_lecture_text` |
| `LLM_MAX_TOKENS` | 4096 | — | потолок completion (SSML-split его не использует) |
| `LLM_PROVIDER_ORDER` | (пусто) | StreamLake | пин upstream-провайдера Polza/OpenRouter |
| `REGEN_LLM_MODEL` | qwen3:8b | как LLM_MODEL | модель полировки при regen одного слайда |

### Vision LLM

| Переменная | Дефолт (config.py) | Использование |
|---|---|---|
| `VISION_PROVIDER` | ollama | `ollama` (любой OpenAI-совместимый, вкл. Polza) или `yandex` |
| `VISION_MODEL` | qwen2-vl:7b | имя модели (`.env.example`: `qwen/qwen3.6-27b`) |
| `VISION_OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` | endpoint (`.env.example`: Polza) |
| `VISION_API_KEY` | ollama | API-ключ |
| `VISION_REASONING_DISABLED` | false | глушит chain-of-thought (OpenRouter-параметр, только для Polza) |
| `VISION_PROVIDER_ORDER` | (пусто) | пин upstream-провайдера (с fallback) |
| `YANDEX_VISION_MODEL` / `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` | yandexgpt-pro / — / — | для `VISION_PROVIDER=yandex` |

### Параллелизм пайплайна (авто от CPU, env — ручной пин)

| Переменная | Дефолт | Использование |
|---|---|---|
| `CPU_BUDGET` | (авто) | cap ядер для формулы (`constants._derive_concurrency`) в cgroup-контейнерах |
| `TTS_WORKERS` | (авто; 4 на 4 ядрах) | TTS-пул **и** `NUMBER_OF_THREADS` Silero-контейнера — инвариант «оба читают одну переменную» |
| `ENCODE_WORKERS` | (авто) | пул FFmpeg-энкодеров |
| `VIDEO_CONCURRENCY` | (авто) | `celery_video --concurrency` = уроков параллельно |
| `VISION_SUMMARY_CONCURRENCY` | (авто) | параллельные vision-summary вызовы |
| `VISION_TASK_CONCURRENCY` | 1 (compose) | `celery_vision --concurrency` (ручной рычаг) |

### Email / биллинг / админ

| Переменная | Дефолт | Использование |
|---|---|---|
| `EMAIL_PROVIDER` / `RESEND_API_KEY` / `EMAIL_FROM` | resend / (пусто) / Edllm <…> | транзакционные письма; пустой ключ в dev ок (задача ретраится и гаснет) |
| `FRONTEND_URL` | `http://localhost:3000` | базовый URL ссылок в письмах (verify, reset, «видео готово») |
| `ADMIN_API_TOKEN` | (пусто) | shared-secret `/billing/admin/*` (`X-Admin-Token`); пусто = выключено |
| `ALERT_ADMIN_EMAIL` | (пусто) | получатель операционных алертов (зависшие платежи) |
| `YOOKASSA_SHOP_ID` / `YOOKASSA_SECRET_KEY` | (пусто) | пусто → `POST /billing/payments` отвечает 503 |
| `YOOKASSA_RETURN_URL` | (пусто) | redirect после оплаты; пусто → `FRONTEND_URL/billing` |
| `YOOKASSA_SEND_RECEIPT` / `YOOKASSA_VAT_CODE` | false / 1 | чеки 54-ФЗ |
| `YOOKASSA_VERIFY_WEBHOOK_IP` | true | IP-allowlist вебхука (выключать только за WAF) |

### Storage / раздача файлов

| Переменная | Дефолт | Использование |
|---|---|---|
| `STORAGE_BACKEND` | local | `local` или `s3` |
| `STORAGE_PATH` | `/app/storage` | путь local-хранилища в контейнере |
| `BASE_URL` | `http://localhost:8000` | публичный URL backend (подписанные ссылки) |
| `SERVE_STATIC_VIA_NGINX` | false | true (прод): `/files/*` отдаёт nginx, FastAPI только верифицирует подпись; также включает `X-Accel-Redirect` в `/stream` |
| `PUBLIC_FILES_BASE_URL` | (пусто) | домен nginx/CDN для подписанных ссылок; пусто → `BASE_URL` |
| `SIGNED_URL_EXPIRES_IN` | 1800 | TTL подписанных URL (per-type тюнинг в `constants.py`) |
| `S3_ENDPOINT_URL` … `S3_PRESIGNED_URL_EXPIRE_SECONDS` | Yandex OS / 3600 | обязательны при `STORAGE_BACKEND=s3` |

### Наблюдаемость / прочее

| Переменная | Дефолт | Использование |
|---|---|---|
| `SENTRY_DSN` | (пусто) | пусто = Sentry выключен; в проде warning при старте |
| `ENVIRONMENT` / `APP_VERSION` | development / dev | окружение и release для Sentry/логов |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.1 | сэмплинг трейсов |
| `METRICS_ENABLED` | true | `/metrics` + Celery-метрики |
| `RUN_MIGRATIONS_ON_STARTUP` | true | dev: авто-`alembic upgrade head` в lifespan; в проде **false** (one-shot `migrate`) |
| `CELERY_FLOWER_USER` / `CELERY_FLOWER_PASSWORD` | admin / change-me | basic-auth Flower |
| `CORS_ORIGINS` | `["http://localhost:3000", …]` | JSON-массив или CSV; `*` в проде — hard error |
| `NUXT_PUBLIC_API_BASE` | `/api/v1` | база API фронта (прод: абсолютный URL за nginx) |

### Только прод (`.env.prod.example`)

| Переменная | Пример | Использование |
|---|---|---|
| `BACKEND_IMAGE` / `FRONTEND_IMAGE` | edllm-backend:local | теги образов для prod-compose |
| `GUNICORN_WORKERS` | 4 | число uvicorn-воркеров gunicorn |
| `DOMAIN` | edllm.ru | подставляется envsubst'ом в [nginx/prod.conf.template](../nginx/prod.conf.template) |
| `CERTBOT_EMAIL` | … | email для Let's Encrypt (`deploy/init-letsencrypt.sh`) |
| `BACKUP_INTERVAL_SECONDS` / `BACKUP_RETENTION_DAYS` | 86400 / 7 | сайдкар `db_backup` |

### TTS

| Переменная | Дефолт | Использование |
|---|---|---|
| `TTS_PROVIDER` | silero | `silero` (локальный контейнер) или `polza` (облачный шлюз polza.ai) |
| `SILERO_TTS_URL` | `http://silero-tts:9898` | endpoint TTS-сервиса |
| `SILERO_TTS_VOICE` | xenia | дефолтный голос; в API можно переопределить |
| `POLZA_API_KEY` | (пусто) | Bearer-токен polza.ai; обязателен при `TTS_PROVIDER=polza` |
| `POLZA_BASE_URL` | `https://api.polza.ai/v1` | база OpenAI-совместимого API polza |
| `POLZA_TTS_MODEL` | `openai/tts-1` | slug TTS-модели в каталоге polza |
| `POLZA_DEFAULT_VOICE` | nova | запасной голос openai/tts-1 для имён вне `POLZA_TTS_VOICES` (constants.py) |
| `POLZA_TTS_SPEED` | (не задано) | скорость речи openai/tts-1, 0.25–4.0; не задано = 1.0 |
| `POLZA_TIMEOUT` | 120.0 | таймаут HTTP-запроса синтеза, сек |
| `POLZA_TTS_WORKERS` | 4 | размер TTS-пула пайплайна при `TTS_PROVIDER=polza` |

Голоса openai/tts-1 (валидатор API + дропдаун фронта, источник — `POLZA_TTS_VOICES` в `constants.py`): `alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.

### Storage / URL

| Переменная | Дефолт | Использование |
|---|---|---|
| `STORAGE_PATH` | `/app/storage` | путь хранилища внутри контейнера backend |
| `BASE_URL` | `http://localhost:8000` | публичный URL backend; используется для генерации `video_url` |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | разрешённые origins; принимает JSON-массив или CSV |

---

## 6. Диагностика — что делать, если что-то не работает

### Проблема: backend не стартует, в логах ошибка миграций

```
backend-1 | sqlalchemy.exc.OperationalError: ...
```

Причины:
- БД не успела подняться. Проверить `docker-compose ps` → postgres `healthy`?
- В моделях изменения, но миграция не сгенерирована. Сгенерировать вручную:
  ```bash
  docker-compose exec backend alembic revision --autogenerate -m "..."
  ```

### Проблема: 500 на любом запросе, в логах нет traceback

Раньше так и было из-за `fileConfig` в `alembic/env.py`. Сейчас починено: env.py пропускает `fileConfig`, если в процессе уже есть logging-handlers (т.е. backend инициализировал logging через `basicConfig` в main.py).

Если 500 всё ещё «беззвучный» — проверь:
```bash
docker-compose logs --tail=200 backend | grep -E "(UNHANDLED|Traceback|app\.main)"
```

### Проблема: «No 'Access-Control-Allow-Origin' header» в браузере

Подходит к двум разным причинам:
1. **Реальная CORS-проблема:** проверить `CORS_ORIGINS` в `.env` — содержит ли `http://localhost:3000`?
2. **Маскированная 500:** раньше на 500-ке заголовков не было → выглядело как CORS. Сейчас порядок middleware исправлен, на 500 заголовки есть. Если в DevTools видишь 500 + CORS → это реальная 500, посмотри backend логи.

### Проблема: Vision-анализ возвращает «No text for any of the slides»

```
RuntimeError: Vision LLM returned no text for any of the 12 slides.
Check that model 'qwen2.5vl:7b' is available in Ollama (run: ollama pull qwen2.5vl:7b).
```

Делать буквально:
```bash
ollama pull qwen2.5vl:7b
ollama list   # убедиться что есть
curl http://localhost:11434/api/tags
```

### Проблема: «Silero TTS request failed»

- Контейнер silero-tts ещё качает модель (5+ минут на первый старт). Проверь:
  ```bash
  docker-compose logs silero-tts | tail
  ```
  Должно быть `Settings: ...` и потом готовность.
- Сервис упал. Перезапустить:
  ```bash
  docker-compose restart silero-tts
  ```

### Проблема: «No slides produced» при генерации

- LibreOffice не справился с PPTX. Часто из-за специфичных шрифтов или повреждённого файла. Открой PPTX вручную и пересохрани в LibreOffice → попробуй снова.
- Закончилось место на диске:
  ```bash
  df -h
  docker system df
  ```
- Очистить временные job-директории, если зависли:
  ```bash
  rm -rf backend/storage/video_jobs/
  ```

### Проблема: Frontend не видит типы Nuxt в VS Code

Bind-mount `frontend/node_modules` пуст на хосте на первом запуске. Должен быть авто-сидинг через `docker-entrypoint.sh`. Если не помогло:
```bash
docker-compose down
docker-compose run --rm frontend npm install
docker-compose up
```

---

## 7. Production deployment — что НЕ реализовано

> Текущий проект — MVP. Базовый прод-рантайм уже собран в [docker-compose.prod.yml](../docker-compose.prod.yml) (self-contained, НЕ override dev-compose) + [frontend/Dockerfile.prod](../frontend/Dockerfile.prod). Ниже — что уже реализовано (✅) и что ещё понадобится при росте.
>
> **Порядок деплоя** (из шапки `docker-compose.prod.yml`):
> ```
> docker compose -f docker-compose.prod.yml --env-file .env.prod build
> docker compose -f docker-compose.prod.yml --env-file .env.prod --profile migrate run --rm migrate
> docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
> ```
> **Восстановление из backup:** `... run --rm db_backup sh -c 'pg_restore -c -d "$PGDATABASE" /backups/<file>.dump'`.

| Что нужно | Зачем / статус |
|---|---|
| ✅ **nginx + TLS** | в prod-compose: конфиг рендерится из [nginx/prod.conf.template](../nginx/prod.conf.template) (nginx-образ прогоняет `envsubst`, подставляется только `${DOMAIN}` — `NGINX_ENVSUBST_FILTER`); certbot — профиль `certbot` + [deploy/init-letsencrypt.sh](../deploy/init-letsencrypt.sh) + systemd-таймер в [deploy/systemd/](../deploy/systemd/). `/files/*` — напрямую с диска, видео — через `X-Accel-Redirect` (`/protected-media/`), Flower за `/flower`, Grafana за `/grafana` |
| ✅ **production frontend** | реализовано в [frontend/Dockerfile.prod](../frontend/Dockerfile.prod): `nuxt build` → `node .output/server/index.mjs`. Dev-compose остаётся на `nuxt dev` |
| ✅ **production uvicorn** | реализовано в `docker-compose.prod.yml`: `gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers N`, без `--reload`. Dev остаётся на `--reload` |
| ✅ **миграции отдельным шагом деплоя** | `RUN_MIGRATIONS_ON_STARTUP=false` (prod) + one-shot сервис `migrate` (`alembic upgrade head`) в `docker-compose.prod.yml`, запускается ДО `up`. Dev: авто-`upgrade head` в lifespan |
| ✅ **Backup БД** | сайдкар `db_backup`: периодический `pg_dump -Fc` → volume `db_backups`, ретенция `BACKUP_RETENTION_DAYS`. Off-host копия в Object Storage — post-MVP |
| ✅ **healthchecks воркеров** | prod-compose: `celery inspect ping` на каждом воркере (общий anchor). В dev-compose healthcheck только у postgres |
| ✅ **Sentry** | инициализирован в `main.py` и `celery_app.py`; включается заданием `SENTRY_DSN`. `before_send` отбрасывает sub-500 HTTPException |
| ✅ **Prometheus / Grafana** | `prometheus-fastapi-instrumentator` (`/metrics`), Celery-метрики через сигналы, DB-backed `UsageCostCollector`; дашборды в `monitoring/` |
| ✅ **S3-бекенд (код)** | `storage_service` умеет `STORAGE_BACKEND=s3` (Yandex OS/совместимый, presigned URLs). Остался операционный шаг: перенос существующих файлов + `PUBLIC_FILES_BASE_URL` |
| **Secret manager** | `SECRET_KEY`, `REDIS_PASSWORD`, ключи провайдеров — сейчас в `.env.prod`. При росте: Yandex Lockbox / Vault |
| **CI/CD** | сейчас нет. Нужен пайплайн: lint (ruff) → tests (pytest) → docker build → push → deploy |
| **Вынос локального inference** | актуально только при возврате на Ollama: отдельный inference-хост/контейнер с GPU. Облачный дефолт (Polza) снимает вопрос |

---

## 8. Полезные ссылки

- [README.md](../README.md) — короткая выжимка, чтобы быстро вспомнить команды.
- [docker-compose.yml](../docker-compose.yml) — главный конфиг инфры.
- [.env.example](../.env.example) — все переменные окружения с примерами.
- [backend/Dockerfile](../backend/Dockerfile) — содержит много нетривиальной настройки шрифтов и LibreOffice.
- [frontend/Dockerfile](../frontend/Dockerfile) + [frontend/docker-entrypoint.sh](../frontend/docker-entrypoint.sh) — поясняют сидинг node_modules.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — известные ограничения.
