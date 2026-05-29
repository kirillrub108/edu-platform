# DEPLOYMENT — поднятие проекта с нуля

> Только реальные команды, которые работают на текущем коде. Это **dev-флоу**: production-конфиг (nginx, k8s, S3, CI/CD) физически отсутствует в репозитории — про него отдельная секция в конце с пометкой «не реализовано».

---

## 1. Системные требования

| Что | Версия | Зачем |
|---|---|---|
| **Docker Desktop** (Win/Mac) или Docker Engine + Compose v2 (Linux) | 24+ | вся инфра поднимается через docker-compose |
| **Ollama** | latest | локальный LLM-сервер. Запускается **на хосте**, не в Docker. См. https://ollama.com/download |
| **Свободного места на диске** | ~30 GB | Docker-образы + LibreOffice (~500MB) + модели Ollama (qwen3:14b ≈ 9GB, qwen2.5vl:7b ≈ 5GB) + модели Silero (~50MB) |
| **RAM** | 16+ GB | Ollama при инференсе qwen3:14b держит ~10GB; параллельно работают backend, postgres, redis, frontend |
| **CPU** | 4+ ядра | Celery prefork использует 2 worker'а + thread-pool'ы для FFmpeg |

GPU не обязателен (Ollama работает на CPU), но с GPU vision-анализ ускоряется в 5-10 раз.

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

### Шаг 3. Установить и запустить Ollama на хосте

```bash
# 1. Скачать с https://ollama.com/download → установить.
# 2. Проверить, что демон запущен и слушает 11434:
curl http://localhost:11434/api/tags
# должен вернуть JSON со списком моделей (возможно пустым)

# 3. Скачать обе модели:
ollama pull qwen3:14b      # для текстовых задач (split, SSML)
ollama pull qwen2.5vl:7b   # для vision-анализа слайдов
```

Ollama должна остаться запущенной — Docker-контейнеры будут к ней обращаться по `host.docker.internal:11434`.

> **Linux:** `host.docker.internal` по умолчанию не резолвится. Либо используй `--add-host=host.docker.internal:host-gateway` в compose, либо замени `LLM_BASE_URL` и `VISION_OLLAMA_BASE_URL` на `http://172.17.0.1:11434/v1` (адрес docker bridge).

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

1. Открыть http://localhost:3000 → «Начать бесплатно».
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

# Тейлить логи одного сервиса
docker-compose logs -f --timestamps backend
docker-compose logs -f --timestamps celery_worker
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

```bash
# Перезапустить только celery_worker (без backend)
docker-compose restart celery_worker

# Зайти в shell celery (для отладки)
docker-compose exec celery_worker celery -A app.celery_app inspect active

# Очистить очередь
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

Все живут в `.env` в корне проекта.

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
| `REDIS_URL` | `redis://:change-me@redis:6379/0` | broker + result backend для Celery |

> Пароль в `REDIS_URL` должен совпадать с `REDIS_PASSWORD`. Это **отдельные переменные** — рассинхрон вызовет «WRONGPASS» в логах celery_worker.

### JWT

| Переменная | Дефолт | Использование |
|---|---|---|
| `SECRET_KEY` | (нужно поменять) | подпись JWT, HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | срок жизни access |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | срок refresh |

### LLM (текстовый)

| Переменная | Дефолт | Использование |
|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI-совместимый endpoint |
| `LLM_MODEL` | qwen3:14b | имя модели |
| `LLM_API_KEY` | ollama | для Ollama любая строка; для YandexGPT — IAM-токен |
| `LLM_TEMPERATURE` | 0.7 | для `enhance_lecture_text` |
| `LLM_MAX_TOKENS` | 2048 | для всех LLM-вызовов |

### Vision LLM

| Переменная | Дефолт | Использование |
|---|---|---|
| `VISION_PROVIDER` | ollama | `ollama` или `yandex` |
| `VISION_MODEL` | qwen2.5vl:7b | имя модели для ollama |
| `VISION_OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` | endpoint |
| `VISION_API_KEY` | ollama | API-ключ |
| `YANDEX_VISION_MODEL` | yandexgpt-pro | имя модели для yandex |
| `YANDEX_FOLDER_ID` | (пусто) | folder_id для Yandex Cloud |
| `YANDEX_API_KEY` | (пусто) | Api-Key для Yandex |

### TTS

| Переменная | Дефолт | Использование |
|---|---|---|
| `TTS_PROVIDER` | silero | пока поддерживается только silero |
| `SILERO_TTS_URL` | `http://silero-tts:9898` | endpoint TTS-сервиса |
| `SILERO_TTS_VOICE` | xenia | дефолтный голос; в API можно переопределить |

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

> Текущий проект — MVP. Для прода понадобится сделать дополнительно. Здесь — список того, чего не хватает, без готовых конфигов.

| Что нужно | Зачем |
|---|---|
| **nginx / cloud LB** перед backend и frontend | TLS termination, gzip/br, `/files/*` через `X-Accel-Redirect`, rate-limiting |
| **build production frontend** | сейчас в compose `nuxt dev`. Для прода: `nuxt build` → `node .output/server/index.mjs` (или статика, если генерить). Меняется Dockerfile и compose-команда |
| **production uvicorn** | сейчас `--reload`. Для прода: `uvicorn app.main:app --workers N --host 0.0.0.0 --port 8000` без `--reload`, желательно через `gunicorn -k uvicorn.workers.UvicornWorker` |
| **миграции отдельным шагом деплоя** | сейчас `alembic upgrade head` в `lifespan`. В проде это опасно (тяжёлая миграция → backend не стартует). Нужен kubectl Job или ci-step |
| **S3 / Yandex Object Storage** | заменить локальный `storage_service.save_upload` на S3-bucket. Структура `pptx/<uuid>_*.pptx`, `videos/<uuid>.mp4` останется, ссылки — presigned URLs |
| **Sentry** | для error-tracking. Подключается через `sentry-sdk[fastapi]` |
| **Prometheus / Grafana** | для метрик. Хотя бы `prometheus-fastapi-instrumentator` |
| **Secret manager** | `SECRET_KEY`, `REDIS_PASSWORD`, `YANDEX_API_KEY` — сейчас в `.env`. В проде: AWS Secrets Manager / Yandex Lockbox / Vault |
| **CI/CD** | сейчас нет. Нужен пайплайн: lint (ruff) → tests (pytest) → docker build → push → deploy |
| **HTTPS-only cookies** | для миграции с localStorage на httpOnly cookie (см. AUTH_FLOW.md) |
| **Backup БД** | автоматический pg_dump в S3 / Object Storage по расписанию |
| **Volume для Ollama** | в проде Ollama не должна быть на хосте. Запускать в отдельном контейнере с GPU или вообще выносить на отдельный inference-сервер |

---

## 8. Полезные ссылки

- [README.md](../README.md) — короткая выжимка, чтобы быстро вспомнить команды.
- [docker-compose.yml](../docker-compose.yml) — главный конфиг инфры.
- [.env.example](../.env.example) — все переменные окружения с примерами.
- [backend/Dockerfile](../backend/Dockerfile) — содержит много нетривиальной настройки шрифтов и LibreOffice.
- [frontend/Dockerfile](../frontend/Dockerfile) + [frontend/docker-entrypoint.sh](../frontend/docker-entrypoint.sh) — поясняют сидинг node_modules.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — известные ограничения.
