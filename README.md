# Edu Platform — AI для учебного контента

SaaS-платформа: преподаватель загружает PPTX/PDF и текст доклада → система генерирует видеолекцию с озвучкой → курс публикуется студентам.

## 1. О проекте

Платформа автоматизирует рутину создания видеокурсов:
- автоматическая нарезка текста доклада по слайдам через LLM;
- TTS-озвучка каждого слайда;
- сборка готового MP4 (LibreOffice + FFmpeg);
- доступ для студентов по ссылке/коду, прогресс и тесты.

## 2. Архитектура

| Компонент    | Технология                          | Назначение                                 |
|--------------|-------------------------------------|--------------------------------------------|
| Backend      | FastAPI 0.136 + SQLAlchemy 2 (async)| HTTP API, бизнес-логика                    |
| БД           | PostgreSQL 17                       | пользователи, курсы, уроки, прогресс       |
| Очередь      | Celery 5.6 + Redis 7                | пайплайн генерации видео в фоне            |
| LLM          | OpenAI-совместимый (Ollama/YandexGPT)| разбиение текста, генерация скриптов и тестов |
| TTS          | заглушка (готов интерфейс)          | синтез речи                                |
| Конвертация  | LibreOffice headless + FFmpeg       | PPTX → PNG → MP4                           |
| Frontend     | Nuxt 3 + Tailwind CSS               | SPA-кабинет преподавателя и студента       |

Все сервисы поднимаются через `docker-compose`.

## 3. Быстрый старт

```bash
git clone <repo> && cd edu-platform
cp .env.example .env

# 1. Поднять Ollama локально (https://ollama.com/download) и скачать модель
ollama pull qwen3:14b

# 2. Поднять стек
docker-compose up --build

# 3. В отдельном терминале применить миграции
docker-compose exec backend alembic revision --autogenerate -m "init"
docker-compose exec backend alembic upgrade head
```

Открыть:
- Фронтенд: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 4. Переменные окружения

| Переменная                     | Описание                                  | Пример                                                   |
|-------------------------------|-------------------------------------------|----------------------------------------------------------|
| `POSTGRES_USER/PASSWORD/DB`   | креды БД                                  | `edu_user / edu_password / edu_platform`                |
| `DATABASE_URL`                | async-строка подключения                  | `postgresql+asyncpg://edu_user:...@postgres:5432/edu_platform` |
| `REDIS_URL`                   | брокер Celery                             | `redis://redis:6379/0`                                  |
| `SECRET_KEY`                  | ключ подписи JWT                          | `change-me-in-prod`                                     |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | срок жизни access-токена                  | `30`                                                    |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | срок жизни refresh-токена                 | `30`                                                    |
| `LLM_BASE_URL`                | OpenAI-совместимый endpoint               | `http://host.docker.internal:11434/v1` (Ollama)          |
| `LLM_MODEL`                   | имя модели                                | `llama3.1`, `yandexgpt/latest`                          |
| `LLM_API_KEY`                 | ключ                                      | `ollama` (для локального — любая строка)                |
| `TTS_PROVIDER`                | имя провайдера                            | `silero`, `yandex`                                      |
| `STORAGE_PATH`                | путь к локальному хранилищу               | `/app/storage`                                          |
| `BASE_URL`                    | публичный URL backend                     | `http://localhost:8000`                                 |
| `CORS_ORIGINS`                | JSON-список разрешённых origin'ов         | `["http://localhost:3000"]`                             |

## 5. API документация

Все эндпоинты сгруппированы по тегам в Swagger (`/docs`):

- **auth** — регистрация, логин, refresh, текущий пользователь
- **courses** — CRUD курсов, модули, публикация (только для роли `teacher`)
- **lessons** — CRUD уроков, обновление скрипта, постановка задачи генерации видео, статус задачи
- **uploads** — загрузка PPTX и видео
- **students** — запись на курс, мои курсы, прогресс, результаты тестов

OpenAPI JSON: `/openapi.json`.

## 6. Пайплайн генерации видео

```
PPTX (загрузка) ──► LibreOffice (PDF) ──► pdftoppm (PNG)
                                              │
                       LLM (split + script) ──┤
                                              ▼
                               TTS (WAV per slide)
                                              │
                                              ▼
                                 FFmpeg (MP4) ──► storage
```

Шаги:
1. `POST /api/v1/uploads/pptx` — загружаете PPTX, получаете `file_path`.
2. Создаёте урок (`POST /api/v1/lessons/`).
3. `PUT /api/v1/lessons/{id}/script` — закладываете текст лекции.
4. `POST /api/v1/lessons/{id}/generate-video` с `pptx_path` — кладёт задачу в Celery, возвращает `task_id`.
5. Статус: `GET /api/v1/lessons/{id}/task-status/{task_id}` (или просто следите за `lesson.status`: `processing → published / error`).

## 7. Разработка

### Запуск backend без Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # или .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://edu_user:edu_password@localhost:5432/edu_platform
uvicorn app.main:app --reload
```

### Создать новую миграцию

```bash
docker-compose exec backend alembic revision --autogenerate -m "describe change"
docker-compose exec backend alembic upgrade head
```

### Добавить роутер

1. Создать `backend/app/routers/<name>.py`, объявить `router = APIRouter(prefix=..., tags=[...])`.
2. Импортировать и подключить в `app/main.py`: `app.include_router(<name>.router)`.

### Структура папок

```
backend/
  app/
    main.py            # FastAPI app, CORS, статика, lifespan
    config.py          # настройки (pydantic-settings)
    database.py        # async engine, get_db
    dependencies.py    # auth-зависимости (get_current_user, require_*)
    celery_app.py      # инстанс Celery
    models/            # SQLAlchemy ORM-модели
    schemas/           # Pydantic v2 DTO
    routers/           # HTTP-маршруты
    services/          # бизнес-сервисы (LLM, TTS, storage, video, auth)
    tasks/             # Celery-задачи
  alembic/             # миграции
  storage/             # файловое хранилище (PPTX, аудио, видео)
frontend/
  src/
    pages/             # Nuxt-страницы (роутинг файловый)
    components/        # переиспользуемые Vue-компоненты
    composables/       # useAuth, useApi
```

## 8. Переключение провайдеров

### LLM: Ollama → YandexGPT

В `.env`:
```env
LLM_BASE_URL=https://llm.api.cloud.yandex.net/v1
LLM_MODEL=yandexgpt/latest
LLM_API_KEY=<ваш Yandex IAM-токен>
```

`LLMService` использует `openai.AsyncOpenAI` — никакого кода менять не нужно.

### TTS: заглушка → Yandex SpeechKit

Откройте `backend/app/services/tts_service.py` и замените тело `synthesize()`:
1. Вызовите `httpx.AsyncClient` к Yandex SpeechKit API.
2. Запишите полученный аудиопоток в `output_path`.

Интерфейс остаётся прежним — пайплайн `tasks/video_pipeline.py` менять не нужно.

## 9. Дорожная карта

**MVP** (текущее)
- Регистрация, базовый кабинет преподавателя и студента.
- Загрузка PPTX, заглушка TTS, рабочий пайплайн → MP4.
- Простой плеер уроков, отметка прохождения.

**Рост**
- Полноценный TTS (Yandex SpeechKit, голоса).
- Хостинг файлов в S3/Yandex Object Storage.
- Аналитика прогресса, дашборд преподавателя.
- Тесты с автопроверкой и системой оценок.

**Масштаб**
- Multi-tenant (организации, биллинг).
- Совместная работа над курсами, версии лекций.
- Интерактивные элементы: субтитры, поиск по транскриптам, чат-бот по материалам курса.
- ML-рекомендации курсов студентам.
