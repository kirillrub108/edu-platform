# DEPLOYMENT — поднятие проекта с нуля

> Только реальные команды, которые работают на текущем коде. Основной фокус — **dev-флоу** (разделы 1–6). Базовый **production-рантайм уже есть** в репозитории — self-contained [docker-compose.prod.yml](../docker-compose.prod.yml) (gunicorn, nginx+TLS, one-shot `migrate`, сайдкар `db_backup`, certbot) + [frontend/Dockerfile.prod](../frontend/Dockerfile.prod); подробности и порядок деплоя — в разделе 7. То, что ещё НЕ реализовано (S3-переезд, secret manager, off-host backup, вынос Ollama), помечено там же.

---

## 1. Системные требования

| Что | Версия | Зачем |
|---|---|---|
| **Docker Desktop** (Win/Mac) или Docker Engine + Compose v2 (Linux) | 24+ | вся инфра поднимается через docker-compose |
| **LLM+vision-провайдер** | — | дефолт `.env.example` — облако **Polza AI** (нужен только API-ключ `pza_...`). Альтернатива — **Ollama на хосте** (см. шаг 3-Б) |
| **Свободного места на диске** | ~10 GB (облако) / ~30 GB (локальный Ollama) | Docker-образы + LibreOffice (~500MB); модели Ollama добавляют 10–15 GB. Silero (~50MB модель) больше не качается автоматически — см. Шаг 3 |
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

**TTS-провайдер.** `.env.example` по умолчанию ставит `TTS_PROVIDER=silero`, но с 2026-08-12
контейнер `silero-tts` **больше не входит в `docker-compose.yml`/`docker-compose.prod.yml`**
(удалён — некоммерческая лицензия русских моделей Silero, см. [DECISIONS.md §15](DECISIONS.md#15-silero-tts-отдельным-контейнером)).
Со значением по умолчанию первая же генерация видео упадёт на этапе TTS с «Silero TTS request
failed» (connection refused) — контейнеру просто неоткуда взяться. Смени `TTS_PROVIDER` на один
из рабочих из коробки вариантов:

```
TTS_PROVIDER=polza     # тот же облачный шлюз, что и для LLM/vision; нужен POLZA_API_KEY
TTS_PROVIDER=yandex    # Yandex SpeechKit v3; нужен YANDEX_API_KEY (см. Vision LLM выше)
```

Самостоятельный хостинг `silero-tts` по-прежнему возможен (образ `navatusein/silero-tts-service`
никуда не делся), но теперь это ручная работа — поднять контейнер и завести сеть/DNS самому,
через compose это больше не приходит бесплатно. Подробности переменных — раздел 5 «TTS».

### Шаг 4. Поднять весь стек

```bash
docker-compose up --build
```

При первом запуске:
- скачается образ postgres:17-alpine, redis:8-alpine;
- соберётся `backend` (~5 минут — устанавливаются LibreOffice, шрифты, ffmpeg, poppler);
- соберётся `frontend` (~2 минуты — `npm install`);
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

### Ручная выдача кредитов

`backend/app/scripts/grant_credits.py` — CLI для ручного начисления кредитов (саппорт-кейсы,
промо), обёртка над `billing_service.sync_grant_credits`. Ищет пользователя по email
(регистронезависимо), создаёт `CreditAccount`, если его ещё нет, и пишет `CreditTransaction`
с `operation=GRANT`:

```bash
docker-compose exec backend python -m app.scripts.grant_credits user@example.com 500 --reason "promo"
```

---

## 4. Запуск backend без Docker (для дебага под отладчиком)

Иногда удобно запустить FastAPI на хосте, оставив postgres/redis в Docker.

```bash
# 1. Поднять только инфраструктуру
docker-compose up -d postgres redis

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
export TTS_PROVIDER="polza"   # или yandex — silero больше не поднимается автоматически, см. §2 Шаг 3
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
| `TTS_WORKERS` | (авто; 4 на 4 ядрах) | размер TTS-пула пайплайна. Комментарий в `constants.py` описывает его как «инвариант с `NUMBER_OF_THREADS` Silero-контейнера» — это устарело: с 2026-08-12 compose больше не передаёт `TTS_WORKERS` ни одному контейнеру, кроме backend/celery; актуально только при собственном self-host Silero, куда эту переменную придётся прокинуть вручную |
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

`TTS_PROVIDER` выбирает один из трёх живых бэкендов в [tts_service.py](../backend/app/services/tts_service.py):
`silero` | `polza` | `yandex`. Дефолт в `config.py`/`.env.example` остался `silero`, но с 2026-08-12
`docker-compose.yml`/`docker-compose.prod.yml` **больше не поднимают контейнер `silero-tts`**
(см. Шаг 3 в разделе 2 и [DECISIONS.md §15](DECISIONS.md#15-silero-tts-отдельным-контейнером)) —
`.env.prod.example` уже переключён на `TTS_PROVIDER=yandex`, но `.env.example` (dev) всё ещё
указывает `silero` как дефолт и требует ручной правки.

| Переменная | Дефолт | Использование |
|---|---|---|
| `TTS_PROVIDER` | silero | `silero` (self-host, больше не в compose) / `polza` (облачный шлюз polza.ai) / `yandex` (Yandex SpeechKit v3) |
| `SILERO_TTS_URL` | `http://silero-tts:9898` | endpoint TTS-сервиса; DNS-имя `silero-tts` резолвится только если контейнер поднят вручную в той же сети |
| `SILERO_TTS_VOICE` | xenia | дефолтный голос; в API можно переопределить |
| `POLZA_API_KEY` | (пусто) | Bearer-токен polza.ai; обязателен при `TTS_PROVIDER=polza` |
| `POLZA_BASE_URL` | `https://api.polza.ai/v1` | база OpenAI-совместимого API polza |
| `POLZA_TTS_MODEL` | `openai/tts-1` | slug TTS-модели в каталоге polza |
| `POLZA_DEFAULT_VOICE` | nova | запасной голос openai/tts-1 для имён вне `POLZA_TTS_VOICES` (constants.py) |
| `POLZA_TTS_SPEED` | (не задано) | скорость речи openai/tts-1, 0.25–4.0; не задано = 1.0 |
| `POLZA_TIMEOUT` | 120.0 | таймаут HTTP-запроса синтеза, сек |
| `POLZA_TTS_WORKERS` | 4 | размер TTS-пула пайплайна при `TTS_PROVIDER=polza` |
| `YANDEX_API_KEY` | (пусто) | тот же ключ, что и для `VISION_PROVIDER=yandex` (см. Vision LLM выше); обязателен при `TTS_PROVIDER=yandex` |
| `YANDEX_TTS_VOICE` | alena | дефолтный голос SpeechKit v3; список голосов и допустимых амплуа — `YANDEX_TTS_VOICES`/`YANDEX_TTS_ROLES_BY_VOICE` в `constants.py` |
| `YANDEX_TTS_ROLE` | (пусто) | амплуа (`good`/`friendly`/`neutral`) — не у каждого голоса есть все три, см. [DECISIONS.md](DECISIONS.md) |
| `YANDEX_TTS_SPEED` | (не задано) | 0.1–3.0, дефолт при отсутствии per-request `speed` в `VideoGenerateRequest` |
| `YANDEX_TTS_TIMEOUT` | 60.0 | таймаут HTTP-запроса к `tts.api.cloud.yandex.net`, сек |

Голоса openai/tts-1 (валидатор API + дропдаун фронта, источник — `POLZA_TTS_VOICES` в `constants.py`): `alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.

`speed`/`pitch` для Yandex можно также переопределить **на каждую генерацию видео** через
`VideoGenerateRequest` (поля `speed: 0.1–3.0`, `pitch: -1000..1000` — диапазоны из `constants.py`,
персистятся per-version в `lesson_videos.speed`/`lesson_videos.pitch`). Silero и Polza эти хинты
игнорируют — SpeechKit-специфика.

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

Самая частая причина в 2026: `TTS_PROVIDER=silero` — дефолт `.env.example` — но
`docker-compose.yml` больше не поднимает `silero-tts` (см. раздел 2 Шаг 3, раздел 5 «TTS»).
Переключись на `TTS_PROVIDER=polza` или `TTS_PROVIDER=yandex` в `.env` и перезапусти backend/воркеры.

Если контейнер поднят вручную (self-host):
- Проверь, что он ещё качает модель (5+ минут на первый старт):
  ```bash
  docker logs silero-tts | tail
  ```
  Должно быть `Settings: ...` и потом готовность.
- Проверь, что `SILERO_TTS_URL` резолвится из сети `backend`/`celery_video` (свой DNS-name/сеть, не `edu-network` по умолчанию).

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

## 7. Production deployment — что реализовано и что ещё нет

> Текущий проект — MVP. Прод-рантайм собран в [docker-compose.prod.yml](../docker-compose.prod.yml) (self-contained, НЕ override dev-compose) + [frontend/Dockerfile.prod](../frontend/Dockerfile.prod), деплой на push в `master` автоматизирован через GitHub Actions + SSH, и с 2026-08-26 web-слой катится **без простоя** (blue-green, см. [DECISIONS.md](DECISIONS.md) §53).

### 7.0 Разовый переход на blue-green (делается один раз)

До этой правки прод крутился на сервисах `backend`/`frontend`; теперь их нет — есть слоты. Первый деплой сам по себе не сработает: старый контейнер nginx не имеет маунтов `/etc/nginx/upstreams` и `/etc/nginx/maintenance`, поэтому `nginx -t` упадёт на отсутствующем `include`. Разовая последовательность на сервере, **до** первого запуска нового `deploy.sh`:

```bash
cd ~/edllm && git pull --ff-only
C="docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green"

# 1. материализовать генерируемые файлы (в git их нет) — иначе nginx не
#    стартует на отсутствующем include
bash deploy/deploy.sh --init-state blue

# 2. собрать образы под текущий тег (:local)
$C build

# 3. поднять blue-слот. Старые backend/frontend пока живы и держат трафик
$C up -d backend_blue frontend_blue
docker inspect -f '{{.Name}} {{.State.Health.Status}}' edllm-backend-blue edllm-frontend-blue

# 4. пересоздать nginx и prometheus с новыми маунтами и снести осиротевшие
#    контейнеры старых backend/frontend. Здесь будет короткий перерыв —
#    единственный за весь переход
$C up -d --force-recreate --remove-orphans nginx prometheus

# 5. проверить
curl -fsS --resolve edllm.ru:443:127.0.0.1 https://edllm.ru/health
```

Дальше `deploy/deploy.sh <sha>` работает штатно и уже без простоя.

> ⚠️ **`--remove-orphans` и профили.** Запуская `up --remove-orphans`, всегда добавляйте `--profile green`. Без него Compose может посчитать контейнеры выключенного профиля осиротевшими и снести **живой зелёный слот**. Именно поэтому `compose()` в [deploy/lib.sh](../deploy/lib.sh) передаёт `--profile green` всегда.

### 7.1 Как устроен blue-green

`backend` и `frontend` существуют в двух экземплярах — **слотах**:

| Слот | Сервисы | Профиль | Контейнеры |
|---|---|---|---|
| `blue` | `backend_blue`, `frontend_blue` | нет (стартует обычным `up -d`) | `edllm-backend-blue`, `edllm-frontend-blue` |
| `green` | `backend_green`, `frontend_green` | `green` | `edllm-backend-green`, `edllm-frontend-green` |

Трафик в каждый момент обслуживает **ровно один** слот. Отсюда следуют неочевидные ограничения на ручные `docker compose` над прод-стеком — см. 7.7. Наружу слоты портов не публикуют — до них дотягивается только nginx по `edu-network`. Кто именно активен, записано в `nginx/upstreams/active.conf`, который подключается из [nginx/prod.conf.template](../nginx/prod.conf.template) строкой `include /etc/nginx/upstreams/*.conf;`. Переключение = перезапись этого файла + `nginx -t` + **`nginx -s reload`** (не `restart`: reload оставляет уже установленные соединения дожить на старых worker-процессах). Слоты сознательно НЕ заведены в `envsubst` — `NGINX_ENVSUBST_FILTER` остаётся ограниченным `${DOMAIN}`.

Тем же переключением обновляется `monitoring/targets/backend.json` — Prometheus в проде discover'ит живой слот через `file_sd_configs` и перечитывает файл сам (reload не нужен).

> **Оба этих файла — генерируемые и в git НЕ хранятся** (`nginx/upstreams/.gitignore`, `monitoring/targets/.gitignore`). Иначе деплой правил бы версионируемый файл, и рано или поздно `git pull --ff-only` в CI отказался бы мержить поверх локальной правки — заклинив все последующие деплои. Сбрасывать их (`git checkout --`) тоже нельзя: это стёрло бы информацию о живом слоте и увело следующий деплой не туда. Отсутствующий файл восстанавливает `ensure_generated_state` в [deploy/lib.sh](../deploy/lib.sh) — из `~/.edllm-deploy/active_slot`, который переживает свежий клон. Вызывается в начале `deploy.sh`, в `maintenance.sh` и внутри `switch_upstream`.

Источник истины про активный слот — именно `active.conf`; `~/.edllm-deploy/active_slot` его зеркалит и используется как фолбэк. Нет ни того, ни другого (или файл битый) — берётся `blue`.

Образ выбирается одной переменной: `edllm-backend:${IMAGE_TAG:-local}` / `edllm-frontend:${IMAGE_TAG:-local}`. `deploy.sh` экспортирует `IMAGE_TAG=<short_sha>`, а на успехе перетегирует `:local` на этот sha — поэтому ручные команды ниже работают без переменных. **`IMAGE_TAG` в `.env.prod` задавать не нужно.** Старые `BACKEND_IMAGE`/`FRONTEND_IMAGE` больше не читаются.

### 7.2 Порядок автодеплоя

`.github/workflows/ci.yml` (job `deploy`, только push в `master`, после `test` и `frontend`) заходит по SSH и запускает `git pull --ff-only && bash deploy/deploy.sh <short_sha>`. [deploy/deploy.sh](../deploy/deploy.sh) делает:

1. **build** `edllm-backend:<sha>` / `edllm-frontend:<sha>` на сервере;
2. **migration guard** — если `alembic current` ≠ `alembic heads`, ревизии между ними прогоняются через `app.scripts.migration_guard`. Найдены `drop_column`/`drop_table`/`rename`/`alter_column(nullable=False)`/сырой `DROP`—`RENAME` в теле `upgrade()` → **деплой останавливается ДО миграции**, прод продолжает работать на старой версии (см. 7.4);
3. **дамп БД** (`pg_dump -Fc` через сервис `db_backup`) — только если миграции есть;
4. **migrate** (one-shot сервис `migrate`);
5. **поднять целевой слот** (противоположный активному) и дождаться готовности: `docker inspect` по healthcheck обоих контейнеров + кросс-сервисная проба сети изнутри целевого backend;
6. **переключить upstream** на целевой слот → `nginx -t` → `nginx -s reload`;
7. **smoke-test** уже через nginx (`/health` + `/docs`, до 12 попыток по 10 с);
8. **retag `:local`** на новый sha и **пересоздать** Celery-воркеров и flower (`up -d --force-recreate` — именно пересоздать: `restart` не меняет образ);
9. **погасить старый слот** (`compose stop`, дренаж в пределах `stop_grace_period`);
10. записать `active_slot` + `last_good_sha`, почистить старые sha-образы (оставляет 3).

**Что происходит при провале:**

| Где упало | Что делает скрипт | Что видит пользователь |
|---|---|---|
| build / guard / migrate | ничего не поднято, миграция не применена | ничего, прод на старой версии |
| целевой слот не стал healthy | целевые контейнеры удаляются | ничего, трафик на старом слоте |
| `nginx -t` отверг include | include возвращается на предыдущий, целевой слот удаляется | ничего |
| smoke-test после переключения | upstream возвращается на старый слот (он ещё жив), целевой удаляется | ничего |
| воркеры не поднялись | upstream назад + **откат на `last_good_sha`** | короткий перерыв на откате |
| после погашения старого слота | **откат на `last_good_sha`** (пересборки нет, образы локальные) | короткий перерыв на откате |

Job красный в любом из этих случаев — даже если откат прошёл успешно.

### 7.3 Ручные операции

Перед тем как руками трогать контейнеры активного слота, воркеров или `redis`, прочитайте 7.7 — там перечислено, что при этом ломается.

```bash
# ── Ручной деплой (эквивалент шагов 1/3/4 автодеплоя, без guard'а и авто-отката).
#    Работает как раньше: голый `up -d` поднимает blue-слот и всю инфру.
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile migrate run --rm migrate
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# ── Посмотреть оба слота (без --profile green зелёный слот не показывается!)
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green ps

# ── Переключить слот вручную (upstream + nginx reload + prometheus targets).
#    Контейнеры целевого слота должны быть уже подняты.
deploy/deploy.sh --switch green

# ── Восстановить генерируемые файлы (свежий клон / их снёс git pull).
#    Ничего не поднимает и не перезагружает — безопасно до старта контейнеров.
deploy/deploy.sh --init-state          # слот берётся из ~/.edllm-deploy/active_slot
deploy/deploy.sh --init-state blue     # или явно

# ── Проверить логику резолва активного слота (не трогает ни прод, ни репозиторий)
deploy/deploy.sh --self-test

# ── Режим техработ
deploy/maintenance.sh on       # 503 + страница/JSON, /health в обход
deploy/maintenance.sh status   # exit 0 = включен, 1 = выключен
deploy/maintenance.sh off

# ── Восстановление из backup
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm \
  db_backup sh -c 'pg_restore -c -d "$PGDATABASE" /backups/<file>.dump'
```

**Ручной откат**, если авто-откат не отработал: поднять предыдущий sha на активном слоте и переключиться на него.

```bash
export IMAGE_TAG=<предыдущий_short_sha>
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green \
  up -d --force-recreate backend_blue frontend_blue
deploy/deploy.sh --switch blue
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green \
  up -d --force-recreate celery_video celery_vision celery_quiz celery_email_worker flower
```

### 7.4 Разрушающие миграции (expand/contract)

Во время переключения обе версии кода работают против одной БД, поэтому миграция релиза N обязана быть совместима с кодом N-1: **только добавление** — nullable-колонки, новые таблицы, индексы (`CONCURRENTLY`). `DROP` / `RENAME` / `SET NOT NULL` выносятся в следующий релиз. То же правило действует для сигнатур Celery-тасок: новые kwargs — только опциональные с дефолтом, удаление/переименование аргумента и смена очереди — следующим релизом (в проде во время рестарта воркеров новый web и старый воркер сосуществуют).

Если разрушающая правка всё же нужна одним релизом:

```bash
DEPLOY_ALLOW_UNSAFE_MIGRATION=1 bash deploy/deploy.sh <short_sha>
```

Тогда сценарий становится: **maintenance on → дамп → migrate → поднять слот → переключить → maintenance off → smoke**. Пользователи видят страницу техработ, а не 502. О таком релизе стоит предупредить заранее — заполнить `MAINTENANCE_WINDOW_START`/`MAINTENANCE_WINDOW_END`/`MAINTENANCE_MESSAGE` в `.env.prod` и выкатить их обычным (безопасным) деплоем: `GET /api/v1/system/status` начнёт отдавать окно, а `MaintenanceBanner` в шапке покажет его за `MAINTENANCE_NOTICE_HOURS` часов до начала и во время.

### 7.5 Проверка перед первым blue-green деплоем

Второй слот на время переключения добавляет ~2.5 GiB (backend 2g + frontend 512m). Перед первым таким деплоем стоит убедиться, что запас есть:

```bash
free -h
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'
```

Проверка самого zero-downtime — непрерывный `curl` во время деплоя, считающий не-200:

```bash
fails=0; total=0
end=$(( $(date +%s) + 600 ))
while [ "$(date +%s)" -lt "$end" ]; do
  total=$((total+1))
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 https://edllm.ru/health || echo 000)
  [ "$code" = "200" ] || { fails=$((fails+1)); echo "$(date +%T) -> $code"; }
  sleep 0.5
done
echo "non-200: $fails / $total"
```

Ожидаемый результат обычного релиза — `non-200: 0`. Открытая в это время страница урока с активной генерацией должна продолжать показывать прогресс: допустим один обрыв SSE с автопереподключением, но не «ошибка генерации» и не сброс состояния.

### 7.6 Статус компонентов

| Что нужно | Зачем / статус |
|---|---|
| ✅ **CI/CD** | [.github/workflows/ci.yml](../.github/workflows/ci.yml): `lint` (ruff check + format) → `test` (`pytest -m "not slow"`, `--cov-fail-under=70`) + `frontend` (vitest) → `deploy` (только push на `master`) — SSH-автодеплой через `deploy/deploy.sh`, см. 7.2 |
| ✅ **Zero-downtime деплой** | blue-green web-слоты + `nginx -s reload` по сгенерированному include; дренаж через `--graceful-timeout` gunicorn и `stop_grace_period`; см. 7.1 и [DECISIONS.md](DECISIONS.md) §53 |
| ✅ **Защита от несовместимых миграций** | `app.scripts.migration_guard` в `deploy.sh`, обход — только явным `DEPLOY_ALLOW_UNSAFE_MIGRATION=1`; см. 7.4 |
| ✅ **Режим техработ** | флаг-файл + `deploy/maintenance.sh`; nginx отдаёт 503 + `Retry-After` (страница / фиксированный JSON `{"code":"maintenance"}` для `/api/*`), `/health` в обход. Предупреждение заранее — `GET /api/v1/system/status` + баннер в `AppHeader` |
| ✅ **nginx + TLS** | конфиг рендерится из [nginx/prod.conf.template](../nginx/prod.conf.template) (`envsubst` подставляет только `${DOMAIN}`); certbot — профиль `certbot` + [deploy/init-letsencrypt.sh](../deploy/init-letsencrypt.sh) + systemd-таймер в [deploy/systemd/](../deploy/systemd/). `/files/*` — напрямую с диска, видео — через `X-Accel-Redirect` (`/protected-media/`), Flower за `/flower`, Grafana за `/grafana` |
| ✅ **production frontend** | [frontend/Dockerfile.prod](../frontend/Dockerfile.prod): `nuxt build` → `node .output/server/index.mjs`. Dev-compose остаётся на `nuxt dev` |
| ✅ **production uvicorn** | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers N`, без `--reload`, с явными `--timeout`/`--graceful-timeout`. Dev остаётся на `--reload` |
| ✅ **миграции отдельным шагом деплоя** | `RUN_MIGRATIONS_ON_STARTUP=false` (prod) + one-shot сервис `migrate`, запускается ДО подъёма слота. `deploy.sh` пропускает шаг целиком, если ревизий не прибавилось. Dev: авто-`upgrade head` в lifespan |
| ✅ **Backup БД** | сайдкар `db_backup`: периодический `pg_dump -Fc` → volume `db_backups`, ретенция `BACKUP_RETENTION_DAYS`; `deploy.sh` дополнительно снимает разовый дамп перед каждой миграцией. Off-host копия в Object Storage — post-MVP |
| ✅ **healthchecks воркеров** | prod-compose: `celery inspect ping` на каждом воркере (общий anchor). В dev-compose healthcheck только у postgres |
| ✅ **Sentry** | инициализирован в `main.py` и `celery_app.py`; включается заданием `SENTRY_DSN`. `before_send` отбрасывает sub-500 HTTPException |
| ✅ **Prometheus / Grafana** | `prometheus-fastapi-instrumentator` (`/metrics`), Celery-метрики через сигналы, DB-backed `UsageCostCollector`; в проде цель скрейпа — активный слот через `file_sd_configs` ([monitoring/prometheus.prod.yml](../monitoring/prometheus.prod.yml)) |
| ✅ **S3-бекенд (код)** | `storage_service` умеет `STORAGE_BACKEND=s3` (Yandex OS/совместимый, presigned URLs). Остался операционный шаг: перенос существующих файлов + `PUBLIC_FILES_BASE_URL` |
| **Secret manager** | `SECRET_KEY`, `REDIS_PASSWORD`, ключи провайдеров — сейчас в `.env.prod` (и `DEPLOY_SSH_KEY`/`DEPLOY_HOST`/`DEPLOY_USER` в GitHub Secrets). При росте: Yandex Lockbox / Vault |
| **Вынос локального inference** | актуально только при возврате на Ollama: отдельный inference-хост/контейнер с GPU. Облачный дефолт (Polza/Yandex AI Studio) снимает вопрос |

### 7.7 Грабли ручных операций над прод-контейнерами

Прод-стек устроен не так, как dev, и «привычные» команды здесь ломают работающий сайт. Всё ниже — про [docker-compose.prod.yml](../docker-compose.prod.yml); dev-файл в прод-командах не участвует и оверрайдить его нельзя.

**Сервиса `backend` (и `frontend`) не существует.** Есть только слоты:

```bash
# ❌ упадёт: no such service: backend
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d backend

# ✅ имена сервисов — со слотом
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green up -d backend_blue frontend_blue
```

Полный список сервисов, которые бегут на образе `edllm-backend`: `backend_blue`, `backend_green`, `celery_video`, `celery_vision`, `celery_quiz`, `celery_email_worker`, `flower`, `migrate` (one-shot, профиль `migrate`). **Воркер писем — `celery_email_worker`**; `celery_email` — это имя *очереди*, а не сервиса, и `up -d celery_email` тоже упадёт с `no such service`.

**Зелёный слот скрыт профилем, синий — нет.** Профиль объявлен только у `backend_green`/`frontend_green` (`profiles: ["green"]`), поэтому `backend_blue`/`frontend_blue` видны всегда, а зелёные — только с `--profile green` (или `COMPOSE_PROFILES=green` в окружении). Это касается и `ps`, и `config --services`, и `stop`, и `--remove-orphans`:

```bash
# зелёных слотов в выводе НЕТ
docker compose -f docker-compose.prod.yml --env-file .env.prod config --services

# а тут есть
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green config --services
```

Именно поэтому `compose()` в [deploy/lib.sh](../deploy/lib.sh) передаёт `--profile green` безусловно: включённый профиль сам ничего не поднимает, но без него `compose stop backend_green` не найдёт сервис.

**Какой слот живой — не угадывать, а посмотреть.** Источник истины — include, который читает nginx; `~/.edllm-deploy/active_slot` его зеркалит:

```bash
grep 'server backend_' nginx/upstreams/active.conf   # backend_blue или backend_green
cat ~/.edllm-deploy/active_slot                      # фолбэк-зеркало
```

Если контейнер с нужным именем есть, но непонятно, тот ли это compose-проект (например, остался от старой схемы) — проверить по лейблам:

```bash
docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} {{index .Config.Labels "com.docker.compose.service"}}' edllm-backend-blue
```

**Воркеров пересоздавать только с `--no-deps`.** У всех `celery_*` и `flower` объявлен `depends_on: redis (service_healthy)`, поэтому без `--no-deps` Compose возьмётся и за `redis` — а он в проде broker Celery, result backend, хранилище refresh-семейств и чекпоинтов пайплайна (см. [AUTH_FLOW.md](AUTH_FLOW.md), [ARCHITECTURE.md](ARCHITECTURE.md)). Его пересоздание выбивает все сессии и задевает очередь и незавершённые генерации:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile green \
  up -d --force-recreate --no-deps celery_video celery_vision celery_quiz celery_email_worker flower
```

**Активный слот backend руками не пересоздавать.** nginx резолвит `backend_<slot>`/`frontend_<slot>` один раз при загрузке конфига; пересозданный контейнер получает новый IP, и апстрим начинает указывать в никуда — 502 до тех пор, пока nginx не перечитает конфиг. Варианты, по возрастанию предпочтительности:

```bash
# приемлемо: пересоздать и сразу перечитать конфиг (несколько секунд 502)
deploy/deploy.sh --switch "$(grep -o 'blue\|green' nginx/upstreams/active.conf | head -n1)"

# правильно: штатный прогон — поднимет ВТОРОЙ слот и переключит трафик без разрыва
bash deploy/deploy.sh <short_sha>
```

`--switch` на тот же слот перерисовывает include и делает `nginx -t` + `nginx -s reload` — это ровно тот же путь, что и настоящее переключение, только без смены цвета.

**Изменения `.env.prod` применяются пересозданием, а не рестартом.** `.env.prod` подключён через `env_file`, то есть читается в момент создания контейнера. Штатный путь — прогнать деплой (веб-слой переедет без простоя), воркеры при этом пересоздаст сам скрипт:

```bash
bash deploy/deploy.sh <short_sha>
```

Если деплоить нечего (менялся только `.env.prod`), тот же эффект без сборки: пересоздать воркеров с `--no-deps` (команда выше), а веб-слой — через подъём противоположного слота и `--switch` на него, как в ручном откате из 7.3. `docker compose restart` здесь бесполезен — он не перечитывает `env_file`.

---

## 8. Полезные ссылки

- [README.md](../README.md) — короткая выжимка, чтобы быстро вспомнить команды.
- [docker-compose.yml](../docker-compose.yml) — главный конфиг инфры.
- [.env.example](../.env.example) — все переменные окружения с примерами.
- [backend/Dockerfile](../backend/Dockerfile) — содержит много нетривиальной настройки шрифтов и LibreOffice.
- [frontend/Dockerfile](../frontend/Dockerfile) + [frontend/docker-entrypoint.sh](../frontend/docker-entrypoint.sh) — поясняют сидинг node_modules.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — известные ограничения.
