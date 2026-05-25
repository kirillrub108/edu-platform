# DECISIONS — обоснования архитектурных выборов

> Каждая запись — нетривиальное решение в проекте. Формат:
>
> - **Контекст** — что нужно было решить
> - **Решение** — что в итоге выбрано
> - **Альтернативы** — что рассматривалось и почему отказались
> - **Trade-offs** — за что заплатили
>
> Часть решений документирована в комментариях к коду или явных Dockerfile-инструкциях; часть — реконструирована из анализа кода (с пометкой «реконструкция»).

---

## Содержание

1. [Backend: FastAPI + async SQLAlchemy](#1-backend-fastapi--async-sqlalchemy)
2. [Двойной DB-driver: asyncpg + psycopg2](#2-двойной-db-driver-asyncpg--psycopg2)
3. [Celery + Redis для долгих задач](#3-celery--redis-для-долгих-задач)
4. [JWT (HS256) вместо сессий](#4-jwt-hs256-вместо-сессий)
5. [`bcrypt(sha256(password))`](#5-bcryptsha256password)
6. [`eager_defaults=True` на ORM-моделях](#6-eager_defaultstrue-на-orm-моделях)
7. [Auto-applied миграции в `lifespan`](#7-auto-applied-миграции-в-lifespan)
8. [Локальное файловое хранилище вместо S3](#8-локальное-файловое-хранилище-вместо-s3)
9. [Раздача файлов через `StaticFiles` без auth](#9-раздача-файлов-через-staticfiles-без-auth)
10. [LibreOffice headless для PPTX→PDF](#10-libreoffice-headless-для-pptxpdf)
11. [Каскад `LibreOffice → pdftoppm`, не прямой LO→PNG](#11-каскад-libreoffice--pdftoppm-не-прямой-lopng)
12. [DPI 150 для PNG слайдов](#12-dpi-150-для-png-слайдов)
13. [Vision LLM вместо OCR](#13-vision-llm-вместо-ocr)
14. [OpenAI SDK как универсальный клиент к LLM](#14-openai-sdk-как-универсальный-клиент-к-llm)
15. [Silero TTS отдельным контейнером](#15-silero-tts-отдельным-контейнером)
16. [Чанкинг текста перед TTS](#16-чанкинг-текста-перед-tts)
17. [Двойной thread-pool в video_pipeline](#17-двойной-thread-pool-в-video_pipeline)
18. [`silenceremove` на хвосте каждого аудио-сегмента](#18-silenceremove-на-хвосте-каждого-аудио-сегмента)
19. [Concat без перекодирования (stream copy)](#19-concat-без-перекодирования-stream-copy)
20. [Кеш PPTX→PNG по `md5+DPI`](#20-кеш-pptxpng-по-md5dpi)
21. [Vision-summary параллельно, vision-analyze последовательно](#21-vision-summary-параллельно-vision-analyze-последовательно)
22. [SSML, а не plain text для TTS](#22-ssml-а-не-plain-text-для-tts)
23. [LLM split с alignment hints](#23-llm-split-с-alignment-hints)
24. [Nuxt SPA (`ssr: false`)](#24-nuxt-spa-ssr-false)
25. [`useState` Nuxt вместо Pinia](#25-usestate-nuxt-вместо-pinia)
26. [Polling вместо WebSocket / SSE](#26-polling-вместо-websocket--sse)
27. [Порядок middleware: CORS снаружи log_and_catch](#27-порядок-middleware-cors-снаружи-log_and_catch)
28. [Замена эмодзи-шрифтов в LibreOffice через .xcu](#28-замена-эмодзи-шрифтов-в-libreoffice-через-xcu)
29. [Зеркало Yandex Debian в backend Dockerfile](#29-зеркало-yandex-debian-в-backend-dockerfile)
30. [Bind-mount `node_modules` для VS Code типов](#30-bind-mount-node_modules-для-vs-code-типов)

---

## 1. Backend: FastAPI + async SQLAlchemy

**Контекст:** Python web framework для проекта, где вся работа — это либо forwarding к LLM/TTS/FFmpeg, либо CRUD + JWT.

**Решение:** FastAPI 0.136 + SQLAlchemy 2.0 (async) + asyncpg.

**Альтернативы:**
- Django REST Framework — синхронный, тяжёлый, но «батарейки в комплекте». Отказались, потому что 70% работы — это I/O к внешним сервисам, async выигрывает.
- Flask + Flask-RESTful — легковесно, но руками писать OpenAPI и валидацию.
- aiohttp — слишком низкоуровнево.

**Trade-offs:**
- + автогенерация OpenAPI/Swagger (`/docs`) бесплатно.
- + Pydantic-валидация — одна модель и для входа, и для документации.
- + async-стек хорошо работает с asyncpg.
- − fragmented best practices (не такой устоявшийся как Django).
- − async-SQLAlchemy всё ещё сложнее sync-варианта (см. инцидент с `MissingGreenlet` после UPDATE).

---

## 2. Двойной DB-driver: asyncpg + psycopg2

**Контекст:** FastAPI работает в async event loop, Celery worker — в синхронных prefork-процессах.

**Решение:** Web-сторона использует `asyncpg` через `create_async_engine`. Celery-задачи используют синхронный `psycopg2` через `create_engine`. URL преобразуется в `tasks/video_pipeline.py`:

```python
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)
```

**Альтернативы:**
- Использовать async-stack и в Celery (через `asgiref.sync_to_async` или вручную крутить event loop). Отказались — overhead без выгоды, prefork-воркер не выигрывает от async.
- Использовать только sync-stack везде (включая FastAPI). Отказались — теряем async-преимущества для I/O-bound кода (LLM, TTS, БД).

**Trade-offs:**
- + Каждая сторона использует оптимальный для неё стек.
- − Две точки конфигурации (два движка, два пула соединений).
- − Любой, кто попробует `await db.commit()` через `AsyncSession` в Celery-задаче, словит runtime errors. Это стоит документировать (и задокументировано в `tasks/video_pipeline.py`).

---

## 3. Celery + Redis для долгих задач

**Контекст:** генерация видео занимает 1-5 минут, vision-анализ — до 30 минут. Нельзя держать HTTP-запрос открытым.

**Решение:** Celery 5.6 с Redis в роли broker + result backend. Задачи лежат в `app/tasks/`. FastAPI публикует задачу через `task.delay(...)` и возвращает `task_id`. Frontend поллит `/task-status/{task_id}` каждые 2-3 секунды.

**Альтернативы:**
- **ARQ** — async-native, легковеснее. Отказались, потому что у Celery — гигантская экосистема, документация, готовые рецепты для retry/timeout/scheduling.
- **Dramatiq** — современнее Celery. Отказались по той же причине, что и ARQ.
- **RabbitMQ** в роли broker — надёжнее Redis. Отказались — нужен ещё один сервис, плюс result-backend всё равно отдельный. Redis совмещает обе роли.
- **PostgreSQL как broker** (через `pgmq` или `task-tiger`) — экономит контейнер. Отказались — Redis даёт лучший throughput на постановку.

**Trade-offs:**
- + Стандартный паттерн, вся команда знает.
- + Prefork-пул изолирует падения (один таск не валит остальные).
- − Redis как result-backend теряет состояние при рестарте. Workaround: `task_id` хранится в БД, статус восстанавливается из `lesson.status`.
- − Тяжело интегрируется с async-кодом (внутри Celery task'а нельзя нативно `await` — приходится писать `asyncio.run(...)`).

---

## 4. JWT (HS256) вместо сессий

**Контекст:** Аутентификация для SaaS-приложения с teacher/student ролями.

**Решение:** stateless JWT с HS256, пара access (30 мин) + refresh (30 дней). Подпись общим `SECRET_KEY`. Хранятся в `localStorage` фронта, передаются через `Authorization: Bearer <token>`.

**Альтернативы:**
- **Серверные сессии** (Redis-backed) — более безопасно (можно revoke мгновенно), но требует server-state на каждом backend-инстансе. Отказались — лишняя зависимость от Redis в горячем пути.
- **JWT с RS256** — асимметричная подпись, public_key можно раздать для верификации. Отказались — overkill для одного backend-инстанса.
- **OAuth2 / SSO** — для B2B имеет смысл, но MVP не требует.

**Trade-offs:**
- + Stateless: backend можно реплицировать без shared session storage.
- + Простота на старте.
- − Невозможность мгновенного revoke без token-versioning (см. [KNOWN_PROBLEMS.md 1.6](KNOWN_PROBLEMS.md#16-refresh-токен-не-отзывается)).
- − Подпись HS256 общим секретом — если он утёк, все токены подделываемы.

---

## 5. `bcrypt(sha256(password))`

**Контекст:** хеширование паролей перед хранением в БД. У bcrypt лимит входа 72 байта.

**Решение:** SHA-256 пре-хеш → 32 байта → bcrypt с автогенерацией соли.

**Альтернативы:**
- **Просто bcrypt с обрезкой до 72 байт** — пользователь с длинным паролем не получит уведомления о потере хвоста, что плохо.
- **argon2id** — современный стандарт, нет лимита входа, но добавляет ещё одну криптобиблиотеку.
- **scrypt** — тяжёлый по памяти, нет нужды.

**Trade-offs:**
- + Поддерживает любые длинные пароли.
- − **Уязвимо к password-shucking** (см. [KNOWN_PROBLEMS.md 1.3](KNOWN_PROBLEMS.md#13--bcryptsha256password--уязвимо-к-password-shucking)).

**Реконструкция:** в коде нет комментария, поясняющего выбор. Скорее всего, разработчик столкнулся с bcrypt-лимитом и применил «классический» обход без оценки последствий.

---

## 6. `eager_defaults=True` на ORM-моделях

**Контекст:** В моделях с `onupdate=func.now()` (User, Course, Lesson, SlideText) после `await db.commit()` SQLAlchemy помечает `updated_at` как expired (потому что новое значение вычисляется БД и неизвестно Python'у). При сериализации Pydantic'ом этот атрибут пытается лениво подтянуться → в async-контексте → `MissingGreenlet`.

**Решение:** `__mapper_args__ = {"eager_defaults": True}` на каждой такой модели. SQLAlchemy добавляет `RETURNING updated_at` к `UPDATE`-statement и подтягивает значение в-память сразу.

**Альтернативы:**
- **Перечислять все server-side defaults в `db.refresh(obj, attribute_names=[...])`** — было реализовано как первая итерация фикса, но костыль: легко забыть колонку при следующем рефакторе.
- **Делать отдельный SELECT после `commit()`** — лишний round-trip к БД.
- **Использовать `expire_on_commit=True` (дефолт)** — приведёт к ленивым подгрузкам **всех** атрибутов, ещё хуже.

**Trade-offs:**
- + Системный фикс, прозрачен на каждом эндпоинте.
- + Решает проблему и для будущих моделей с `onupdate`.
- − Каждый `UPDATE` теперь имеет `RETURNING` clause — ничтожная нагрузка на БД, но не нулевая.

**Документация:** добавлена в комментарии моделей и обсуждается в [DEVELOPMENT-GOTCHAS](#).

---

## 7. Auto-applied миграции в `lifespan`

**Контекст:** dev-окружение хочет запустить `docker-compose up` и сразу увидеть актуальную схему БД.

**Решение:** в [main.py:_ensure_schema_at_head](../backend/app/main.py) при старте FastAPI выполняется `command.upgrade(cfg, "head")`. Это заменило старый бутстрап через `Base.metadata.create_all`, который не обновлял alembic_version и потом ломал ручные миграции.

**Альтернативы:**
- **`Base.metadata.create_all`** — старый подход. Отказались — рассинхронизация с alembic-историей.
- **Ручной `docker-compose exec backend alembic upgrade head`** при первом старте — добавляет шаг в README.
- **Отдельный compose-сервис `migrate`** с `depends_on: postgres healthy` — самый чистый вариант, но усложнение для dev.

**Trade-offs:**
- + Dev-удобство.
- − В проде это опасно (см. [KNOWN_PROBLEMS.md 5.1](KNOWN_PROBLEMS.md#51-миграции-запускаются-в-lifespan)).

---

## 8. Локальное файловое хранилище вместо S3

**Контекст:** где хранить загруженные PPTX, сгенерированные MP4, PNG слайдов.

**Решение:** локальная директория `backend/storage/` (volume в docker). `storage_service.save_upload(...)` пишет туда, `get_url(...)` возвращает `BASE_URL/files/<path>`.

**Альтернативы:**
- **S3 / Yandex Object Storage** — правильно для прода. Отказались для MVP — лишняя инфраструктура (бакет, IAM, presigned URLs).
- **NFS-volume** — если backend будет масштабироваться горизонтально. Не нужно на MVP.

**Trade-offs:**
- + Простой dev-опыт.
- + Никаких внешних зависимостей.
- − Не масштабируется (две backend-реплики не видят файлов друг друга).
- − Потеря volume = потеря всех файлов.

**Mitigation:** интерфейс `StorageService` уже абстрактный (`save_upload`, `get_url`, `get_full_path`, `delete_file`). Когда понадобится S3 — добавить второй класс, переключать через env.

---

## 9. Раздача файлов через `StaticFiles` без auth

**Контекст:** студент должен видеть видео-файл в своём `<video src="...">`. Преподаватель — слайды-PNG в редакторе.

**Решение:** `app.mount("/files", StaticFiles(directory=settings.STORAGE_PATH))`. Все файлы — публичны.

**Альтернативы:**
- **Авторизованный proxy-эндпоинт** `GET /files/{path}` с проверкой прав → стрим. Безопаснее, но добавляет CPU-overhead.
- **Presigned URLs** (если на S3) — самый правильный для прода.

**Trade-offs:**
- + Простой код, FastAPI просто стримит файлы.
- − **Любой со ссылкой может скачать чужой контент** (см. [KNOWN_PROBLEMS.md 1.4](KNOWN_PROBLEMS.md#14--files-отдаётся-без-auth-проверки)).

---

## 10. LibreOffice headless для PPTX→PDF

**Контекст:** нужно конвертировать PPTX в формат, пригодный для рендеринга в PNG.

**Решение:** `libreoffice --headless --convert-to pdf` через subprocess.

**Альтернативы:**
- **python-pptx** — умеет читать XML, но **не рендерить**. Отказались — не подходит.
- **Aspose.Slides** — коммерческая. Отказались — лицензия.
- **Microsoft Graph API / Office 365** — требует Microsoft-аккаунт + платный API.
- **Прямой парсинг XML + ручной рендеринг через Pillow** — переизобретение. Полностью отказались.

**Trade-offs:**
- + Бесплатно и работает.
- + Поддерживает большинство шрифтов и эмодзи.
- − Тяжёлый Docker-образ (+500MB).
- − Медленный старт (~5 секунд на каждый запуск).
- − Иногда падает на нестандартных PPTX.
- − Сам по себе stateful (создаёт `_lo_profile/`).

---

## 11. Каскад `LibreOffice → pdftoppm`, не прямой LO→PNG

**Контекст:** надо получить PNG-кадр на каждый слайд PPTX.

**Решение:** `LibreOffice → PDF`, потом `pdftoppm -png -r 150 PDF` → `slide-N.png`.

**Альтернативы:**
- **`libreoffice --convert-to png`** — теоретически делает то же. На практике даёт один PNG на ВСЮ презентацию (как одна страница), не по слайдам.
- **`pdf2image`** (Python wrapper над poppler) — используется в [utils/slide_renderer.py](../backend/app/utils/slide_renderer.py), но это alternative path (мёртвый код).
- **PyMuPDF / fitz** — отдельный native binary в зависимостях. Отказались — `pdftoppm` уже установлен с poppler-utils.

**Trade-offs:**
- + Качественный антиалиасинг, поддержка масштаба через `-r`.
- + Стабильно работает на Linux.
- − Два отдельных процесса subprocess.
- − Если PDF-стадия упала, PPTX-стадия впустую.

**Особый случай:** если входной файл уже PDF — LibreOffice пропускается. PDF подаётся прямо в `pdftoppm`. Сделано потому что прогон PDF через LibreOffice портит шрифты (особенно Cyrillic) — задокументировано в [video_service.py:181-185](../backend/app/services/video_service.py).

---

## 12. DPI 150 для PNG слайдов

**Контекст:** разрешение слайда определяет качество и размер PNG → влияет на скорость FFmpeg-encoding и общий вес видео.

**Решение:** `_SLIDE_DPI = 150` в [video_service.py](../backend/app/services/video_service.py).

**Альтернативы:**
- **300 DPI** — стандарт печати. На 1080p экране визуально неотличимо от 150, но PNG в 4 раза тяжелее.
- **96 DPI** — стандарт экрана. Видны артефакты антиалиасинга на текстах.

**Обоснование (закомментировано в коде):**
> 150 DPI is indistinguishable from 300 DPI on a 1080p screen but produces 4× smaller PNG files and cuts pdftoppm + FFmpeg encoding time significantly.

**Trade-offs:**
- + Быстрее на 30-40% по сравнению с 300.
- − На 4K-экране при просмотре крупным планом будет видно.

---

## 13. Vision LLM вместо OCR

**Контекст:** в auto-режиме надо сгенерировать текст озвучки по тому, что показано на слайде.

**Решение:** Ollama + qwen2.5vl:7b (multimodal). На вход — base64-JPEG слайда, на выходе — связный текст 150-300 слов.

**Альтернативы:**
- **Tesseract OCR** — распознаёт символы. Отказались — буквальный текст со слайда (например, «Преимущества микросервисов: масштабируемость, изоляция, независимый деплой») не работает как озвучка.
- **PaddleOCR + GPT для расширения** — два шага, два сервиса, и всё равно не понимает диаграммы и схемы.
- **YandexGPT-Pro Vision** — поддерживается опционально (через `VISION_PROVIDER=yandex`), но требует Yandex Cloud аккаунт.

**Trade-offs:**
- + Понимает контекст, диаграммы, иконки.
- + Пишет связный educational-style текст.
- − Тяжёлая зависимость на хост (Ollama + 5-9GB модель).
- − 30-60 секунд на слайд при работе на CPU.
- − Качество нестабильно (иногда галлюцинирует).

---

## 14. OpenAI SDK как универсальный клиент к LLM

**Контекст:** проект должен поддерживать локальный LLM (Ollama) для разработчиков и облачный (YandexGPT) для прода.

**Решение:** `from openai import AsyncOpenAI`. Этот SDK совместим с любым OpenAI-compatible эндпоинтом — Ollama (`/v1/chat/completions`) и YandexGPT (через свой API-gateway) оба эмулируют этот формат.

**Альтернативы:**
- **LangChain** — тяжёлая абстракция, добавляет зависимости и слой непонятного.
- **LiteLLM** — заточен под мультипровайдинг, но ещё одна зависимость.
- **Свой HTTP-клиент через httpx** — простой, но дублирует OpenAI-формат вручную.

**Trade-offs:**
- + Один интерфейс — два провайдера, без if-ов.
- + SDK развивается синхронно с OpenAI API (новые фичи приходят бесплатно).
- − Привязка к OpenAI-формату; если в будущем понадобится Anthropic — нужен отдельный код.

---

## 15. Silero TTS отдельным контейнером

**Контекст:** нужен русский TTS для озвучки слайдов.

**Решение:** запускаем готовый docker-образ `navatusein/silero-tts-service` на порту 9898 как отдельный сервис. Backend общается с ним по HTTP.

**Альтернативы:**
- **Встроить Silero в backend-контейнер** через прямой `torch`-импорт. Отказались — torch + модель ~2GB, утяжелит и замедлит backend-образ.
- **Yandex SpeechKit** — качественнее, но платный. Поддержка заглушена в коде (`raise NotImplementedError` в `tts_service.py`).
- **gTTS (Google Text-to-Speech)** — работает, но требует интернет на каждый запрос.
- **eSpeak** — звучит роботизированно, не подходит для educational.

**Trade-offs:**
- + Изолированная зависимость, не утяжеляет backend.
- + Можно скейлить отдельно от backend.
- + Бесплатный, OSS.
- − Ещё один контейнер.
- − HTTP overhead на каждый запрос (vs прямой Python-вызов).

---

## 16. Чанкинг текста перед TTS

**Контекст:** Silero возвращает 500-ку на длинных входах (>1000 chars).

**Решение:** в [tts_service.py:_split_for_tts](../backend/app/services/tts_service.py) текст режется на чанки ≤800 символов на границах предложений (`.`/`!`/`?`/`…`). Если предложение само длиннее — режется по запятым/точкам с запятой. Каждый чанк → отдельный HTTP-запрос → склейка через `_concat_wav`.

**Альтернативы:**
- **Слать как есть, ловить 500** — теряем слайд.
- **Ограничить текст слайда жёстко** на этапе LLM-промпта — недоверие к модели, возможны срезы.

**Trade-offs:**
- + Гарантирует, что любой длины текст озвучится.
- − Лишний overhead на склейку WAV (но это копеечная операция).

---

## 17. Двойной thread-pool в video_pipeline

**Контекст:** на пайплайне «PPTX → MP4» есть два этапа, оба с естественным параллелизмом — TTS (HTTP-запросы к Silero) и encoding (FFmpeg). Если делать последовательно (TTS всех → encode всех), общее время = sum(TTS) + sum(encode).

**Решение:** [tasks/video_pipeline.py:217-251](../backend/app/tasks/video_pipeline.py) запускает два `ThreadPoolExecutor` — `tts_pool=4` и `enc_pool=3` — и через цепочку `as_completed` подаёт результат TTS K-го слайда сразу в encoding.

**Альтернативы:**
- **Последовательно** — медленно (~30% дольше).
- **Один большой thread-pool** — TTS и encoding конкурируют за слоты, нет фиксированного баланса.
- **Asyncio с `asyncio.gather`** — нельзя, потому что Celery prefork не async; FFmpeg всё равно subprocess.

**Trade-offs:**
- + ~30% выигрыша по времени на типичной презентации.
- − Сложный concurrency-код, трудно отлаживать.
- − Жёсткие константы (`_TTS_WORKERS=4` совпадает с `NUMBER_OF_THREADS=4` Silero — рассинхрон сломает).

---

## 18. `silenceremove` на хвосте каждого аудио-сегмента

**Контекст:** Silero часто оставляет 0.3-0.5 секунд тишины в конце аудио. При склейке с FFmpeg получаются «дёргания» при переходе на следующий слайд.

**Решение:** [video_service.py:_trim_trailing_silence](../backend/app/services/video_service.py) — FFmpeg фильтр `silenceremove=stop_periods=-1:stop_duration=0.15:stop_threshold=-40dB`. Если результат <0.1s — fallback на оригинал.

**Альтернативы:**
- **Не обрезать** — видеоряд кажется «рваным» на стыках слайдов.
- **Кросс-фейд между сегментами** — нужно перекодировать, дороже.

**Trade-offs:**
- + Видео визуально плавнее.
- − Дополнительная FFmpeg-команда на каждый слайд.

---

## 19. Concat без перекодирования (stream copy)

**Контекст:** склейка отдельных слайдов-сегментов в финальный MP4.

**Решение:** [video_service.py:concatenate_segments](../backend/app/services/video_service.py) использует `ffmpeg -f concat -c copy ...` — байтовое склеивание без повторного encoding.

**Альтернативы:**
- **Concat с перекодированием** (`-c:v libx264 -c:a aac`) — даёт смешение разных параметров, но в 5-10 раз медленнее.
- **Filter_complex с `concat` filter** — нужно для смены параметров, но опять — encoding.

**Trade-offs:**
- + Быстрая склейка (~1 секунда даже на длинной презентации).
- − Все сегменты должны иметь одинаковые параметры (frame rate, codec, container). Для этого encode_segment жёстко задаёт `25 fps, libx264, aac, 192kbps, 48kHz, yuv420p`.

---

## 20. Кеш PPTX→PNG по `md5+DPI`

**Контекст:** один и тот же PPTX может конвертироваться многократно (повторная генерация, vision-анализ + затем video).

**Решение:** [video_service.py:_pptx_cache_key](../backend/app/services/video_service.py) — `md5(content)+DPI` → имя кеш-папки в `storage/slides_cache/`. Если есть — возвращается список PNG, минуя LibreOffice + pdftoppm.

**Альтернативы:**
- **Кеш по `lesson_id`** — теряет общность (если два урока загрузили тот же файл).
- **Кеш по mtime файла** — недостоверно (mtime меняется при копировании).
- **Без кеша** — повторная генерация на 30+ секунд медленнее.

**Trade-offs:**
- + Огромная экономия времени на повторных запусках.
- + Cross-lesson reuse (если два пользователя загрузили один и тот же ppt).
- − Растёт без TTL (см. [KNOWN_PROBLEMS.md 2.8](KNOWN_PROBLEMS.md#28-кеш-слайдов-растёт-бесконечно)).

---

## 21. Vision-summary параллельно, vision-analyze последовательно

**Контекст:** в проекте два разных vision-флоу.

**Решение:**
- `summarize_presentation` (alignment hint в manual-режиме) — параллельный, `asyncio.Semaphore(4)`. Каждый слайд анализируется независимо, потому что нужна **краткая характеристика** (2-4 предложения), не связное повествование.
- `analyze_presentation` (auto-режим) — последовательный. Каждому слайду в промпт даётся `previous_context` (последние 3 слайда), чтобы повествование текло связно: «как мы видели на предыдущем слайде…».

**Альтернативы:**
- **Оба параллельно** — потеря связности в auto-режиме.
- **Оба последовательно** — медленно.

**Trade-offs:**
- + Каждый режим оптимизирован под свою цель.
- − Два разных pattern в одном сервисе. Понимание разницы требует комментария.

---

## 22. SSML, а не plain text для TTS

**Контекст:** Silero TTS поддерживает SSML-теги (`<p>`, `<break>`, `<prosody>`).

**Решение:** LLM-split возвращает текст, обёрнутый в `<p>...</p>` с `<break time="500ms"/>` между мыслями и `<prosody rate="slow">` вокруг технических терминов. Перед отправкой в TTS — `_strip_ssml_tags` очищает обратно (Silero не умеет SSML напрямую, но мы используем структуру для разбивки и форматирования).

**Реконструкция:** в `_SSML_SYSTEM` промпт SSML-теги задействованы, но в `tts_service` они снова стрипаются. Похоже, текущий Silero-сервис не интерпретирует их, и SSML здесь — внутренний формат для будущей интеграции с провайдером, который поддерживает SSML (Yandex SpeechKit, AWS Polly).

**Trade-offs:**
- + Готовность к проще-апгрейду провайдера.
- − Сейчас лишняя работа (генерим, потом стрипаем).
- − Если LLM выдаёт invalid XML — есть риск сломать TTS.

---

## 23. LLM split с alignment hints

**Контекст:** разбить лекцию (один сплошной текст) на N кусков, ровно соответствующих слайдам.

**Решение:** [llm_service.py:split_and_annotate_ssml](../backend/app/services/llm_service.py). На вход — `script` + `slides_count` + `slide_texts` (краткие саммари каждого слайда от vision-LLM, сделанные `summarize_presentation`). LLM использует саммари как «якорь» — где в тексте начинаются темы каждого слайда.

**Альтернативы:**
- **Делить по равной длине** — фолбэк (`_fallback_ssml`), часто неверный.
- **Делить по предложениям и брать N равных групп** — то же самое, что fallback.
- **Слепо доверять LLM без слайд-саммари** — LLM плохо угадывает, какая часть текста про какой слайд (особенно если в скрипте нет явных «На третьем слайде…»).

**Trade-offs:**
- + Качественная синхронизация скрипта и слайдов.
- − Лишний шаг (vision-summarize) перед LLM-split. На 30-слайдовой презентации — +2 минуты.
- − При невалидном JSON ответе — fallback ухудшает качество ([KNOWN_PROBLEMS.md 2.5](KNOWN_PROBLEMS.md#25-llm-возвращает-не-n-чанков--fallback-ухудшает-качество)).

---

## 24. Nuxt SPA (`ssr: false`)

**Контекст:** какая модель рендеринга для frontend.

**Решение:** Nuxt 3 в SPA-режиме (`nuxt.config.ts: ssr: false`). Сборка даёт статический HTML+JS, который рендерится в браузере.

**Альтернативы:**
- **Полный Nuxt SSR (`ssr: true`)** — сервер рендерит первый кадр. Преимущества: SEO, быстрее first paint. Отказались — для B2B-продукта (преподаватели, студенты с логином) SEO неактуален, а добавление Node-сервера в продакшене усложняет деплой.
- **Чистый Vue 3 + Vite** — без Nuxt. Отказались — потеряли бы file-based routing, auto-imports, composables.
- **React** — обширнее экосистема, но команда (видимо) выбрала Vue.

**Trade-offs:**
- + Деплой как статика.
- + Простой dev-сервер.
- + File-based routing бесплатно.
- − Slow first paint (надо подождать загрузку JS-bundle).
- − Никакого SSR-кеша.

---

## 25. `useState` Nuxt вместо Pinia

**Контекст:** глобальное реактивное состояние во фронте.

**Решение:** встроенный `useState('key', factory)`. Используется для:
- `'auth.user'` — текущий пользователь.
- `'creation.mode'` — выбранный режим создания урока.

**Альтернативы:**
- **Pinia** — стандарт для Vue. Отказались — overkill для двух глобальных значений.
- **Vuex 4** — устарел.
- **Передача props через все компоненты** — невозможно (компоненты на разных страницах).

**Trade-offs:**
- + Нулевая зависимость.
- + Минимальный код.
- − При росте сложности (десятки global state) — придётся мигрировать на Pinia.
- − Нет devtools-инспекции (Pinia интегрирована с Vue Devtools).

---

## 26. Polling вместо WebSocket / SSE

**Контекст:** фронту нужно узнавать о завершении долгих задач (генерация видео, анализ слайдов).

**Решение:** `setInterval(pollStatus, 2000-3000)` → `GET /task-status/{task_id}` или `GET /lessons/{id}`.

**Альтернативы:**
- **WebSocket** — более эффективно (push, не pull). Отказались — нужен дополнительный auth-флоу для WS, более сложное масштабирование (sticky session или Pub/Sub).
- **Server-Sent Events (SSE)** — проще WebSocket, но всё равно требует поддержки на стороне load balancer.
- **Long-polling** — компромисс между простотой и push-семантикой.

**Trade-offs:**
- + Простой код на фронте и бэке.
- + Работает через любой proxy/CDN без настройки.
- + При закрытии вкладки автоматически прекращается.
- − Лишние HTTP-запросы каждые 2-3 секунды (нагрузка на backend).
- − Задержка обновления статуса до интервала polling'а.

---

## 27. Порядок middleware: CORS снаружи log_and_catch

**Контекст:** при 500-ке (например, ResponseValidationError при сериализации) браузер не получал CORS-заголовков → ошибка маскировалась под «CORS policy».

**Решение:** в [main.py](../backend/app/main.py) сначала регистрируется `@app.middleware("http") log_and_catch`, **потом** `app.add_middleware(CORSMiddleware, ...)`. В современной Starlette `add_middleware` делает `insert(0, ...)` — последний добавленный становится самым внешним. Итог: `ServerError → CORS → log_and_catch → ExceptionMiddleware → routes`.

**Альтернативы:**
- **Использовать `@app.exception_handler(Exception)`** — не подходит, потому что он живёт в ExceptionMiddleware (внутри стека) и для генерических Exception не вызывается (только для HTTPException).
- **Регистрировать CORS первым** — было до фикса. CORS оказывался **внутри** log_and_catch → 500-ка теряла заголовки.

**Trade-offs:**
- + Любой 500 теперь приходит к клиенту с CORS-заголовками. Браузер показывает реальную ошибку.
- + Никаких лишних middleware.

**Документация:** длинный комментарий в `main.py:71-87`.

---

## 28. Замена эмодзи-шрифтов в LibreOffice через .xcu

**Контекст:** PPTX часто содержат эмодзи в шрифтах `Segoe UI Emoji` (Windows) или `Apple Color Emoji` (Mac). В Linux-контейнере этих шрифтов нет → LibreOffice показывает квадратики.

**Решение:** [backend/lo-emoji-substitution.xcu](../backend/lo-emoji-substitution.xcu) — XML-маппинг шрифтов. На каждый запуск LibreOffice [video_service.py:_seed_lo_profile](../backend/app/services/video_service.py) копирует этот файл в свежий `_lo_profile/user/registrymodifications.xcu`.

**Альтернативы:**
- **Установить Microsoft Core Fonts** в Dockerfile — частично помогает (для основных шрифтов), но Segoe Emoji из них не входит.
- **Не делать ничего** — квадратики на слайдах с эмодзи.
- **Использовать `fontconfig` aliasing** — менее предсказуемо.

**Trade-offs:**
- + Работает.
- − Хрупкий (если LibreOffice сменит формат `.xcu` — поломается).
- − `_seed_lo_profile` нужно вызывать перед **каждым** запуском LibreOffice, иначе эмодзи не подменятся.

---

## 29. Зеркало Yandex Debian в backend Dockerfile

**Контекст:** при сборке backend-образа `apt-get install` грузит сотни мегабайт пакетов с Debian-зеркал. Стандартный `deb.debian.org` через Fastly CDN рвёт коннекты на длинных запросах из RU-сетей.

**Решение:** [backend/Dockerfile:13-19](../backend/Dockerfile) — `sed`-замена URL-ов на `mirror.yandex.ru` плюс aggressive retry config (`Acquire::Retries "10"`).

**Альтернативы:**
- **Не менять зеркало** — рискованно для разработчиков из РФ.
- **Использовать pre-built образ с уже установленным LibreOffice** — менее гибко.

**Trade-offs:**
- + Сборка стабильна для RU-разработчиков.
- − Зависимость от конкретного зеркала. Если оно упадёт — нужен fallback.

---

## 30. Bind-mount `node_modules` для VS Code типов

**Контекст:** разработчик пишет фронт в VS Code на хосте. Контейнер frontend поднят в Docker. VS Code должен видеть TypeScript-типы (включая Nuxt-сгенерированные `.nuxt/types/*`).

**Решение:**
- В [docker-compose.yml](../docker-compose.yml) bind-mount `./frontend/node_modules:/app/node_modules` и `./frontend/.nuxt:/app/.nuxt`.
- В [frontend/Dockerfile](../frontend/Dockerfile) после `npm install` снимается snapshot — `cp -a /app/node_modules /opt/node_modules_baked`.
- В [frontend/docker-entrypoint.sh](../frontend/docker-entrypoint.sh) при первом старте, если bind-mount пуст (первая сборка) — снепшот копируется на хост.

**Альтернативы:**
- **Не bind-mount'ить `node_modules`** — VS Code не видит типов, разработка вслепую.
- **`npm install` на хосте отдельно** — версии могут разойтись с контейнером.

**Trade-offs:**
- + VS Code работает идеально.
- + Контейнер и хост видят одинаковые модули.
- − Первый старт сидит модули (~30 секунд).
- − Если на хосте Linux ≠ контейнерному Linux (например, native modules для macOS arm64 vs Linux x86_64) — будет несовместимость. На практике для Nuxt не страшно, но риск есть.

---

## 31. AI-генерация и редактирование тестов (quiz authoring)

**Контекст:** преподаватель хочет получить проверочный тест по уроку автоматически из материалов (слайды / скрипт), редактировать вопросы вручную или с AI-помощью, и прогонять AI-проверку перед публикацией.

**Решение:**
- **Очередь Celery — `vision`** (а не `video`). Задача упирается в LLM-провайдер, который и так делит concurrency с vision-пайплайном (Ollama одна на весь хост). `video`-очередь зарезервирована под FFmpeg/TTS и параллелит concurrency=2 — туда вешать LLM-задачи нельзя без переподписки.
- **Replace, не versioning.** Celery-таск удаляет старые `QuizQuestion` и вставляет новые в одной транзакции; вопросы вне основного workflow не существуют (студент берёт тест только после публикации видео), поэтому история не нужна.
- **QA-проверка — отдельный синхронный endpoint без записи в БД.** Идемпотентна, дешева для повтора, не блокирует UI; flags возвращаются для отображения, решение о правке принимает преподаватель.
- **Приоритет материала:** `SlideText.edited_text ?? generated_text` (отсортированные по `slide_number`) → `lesson.script` → `lesson.text_content`. Финальная озвучка точнее любой ручной заметки, поэтому она первая.

**Trade-offs:**
- + Один LLM-rate-limit, единый бэк-прешшур через очередь `vision`.
- + Простая транзакционная семантика и понятный UX («перегенерировать заменит существующее»).
- − Если в будущем понадобится A/B-тест версий — нужна миграция на версионирование.
- − QA-проверка повторяет вызов LLM, но при ≤10 вопросах это дешевле, чем хранить флаги в БД с TTL.

---

## 32. Полноценный модуль тестирования: polymorphic JSONB + snapshot + hybrid grading

**Контекст:** Старый тестовый модуль поддерживал только single-choice, сохранял `quiz_score` как float в `lesson_progress` без истории попыток, был привязан к `Lesson` напрямую (без сущности `Quiz`), терял эталоны при редактировании во время сдачи. LLM-генератор галлюцинировал «ГОСТ Р ИСО 2150N» и «548NN». Нужны были 8 типов вопросов, независимая публикация теста от статуса урока, ограничение числа попыток, безопасная гибридная проверка (детерминированная + LLM) с ручным override преподавателя.

**Решение:**

- **Полиморфные вопросы через JSONB + discriminated union**, а не отдельные таблицы на каждый тип. `quiz_questions(type, payload, weight, order)` + Pydantic v2 `Annotated[Union[...], Field(discriminator="type")]`. Параллельные семейства схем `*Teacher*` и `*Student*` — последние без полей-эталонов, чтобы утечка была невозможна на уровне типа (`to_student_payload` вызывается серверно при сериализации, никаких runtime-фильтров).
- **Сущность `Quiz` 1:1 к Lesson** со своим жизненным циклом (`draft|published`), порогом, `attempts_allowed`, `show_answers`, `shuffle`. `Quiz.status` управляется отдельными эндпоинтами `publish/unpublish`, не зависит от `Lesson.status` — преподаватель может опубликовать тест к черновому уроку и наоборот.
- **`QuizAttempt.questions_snapshot` целиком при старте** — JSONB с полным payload’ом всех опубликованных вопросов **на момент старта попытки**, включая эталоны. Это единственный источник правды для оценки данной попытки. Старые попытки остаются валидными, даже если преподаватель в это время перегенерировал/переписал вопросы. Альтернатива «ссылками на live-вопросы» отвергнута: запрет редактирования теста при наличии in-progress попыток замораживал бы UX, а ссылки на удалённые вопросы создавали бы dangling FK.
- **Гибридная проверка**: закрытые типы оцениваются детерминированно в момент `submit` (мгновенный фидбек); открытые (short_answer/essay) помечаются `needs_review=true` и оцениваются LLM-задачей `grade_attempt_task` параллельно через `ThreadPoolExecutor + as_completed` (паттерн `video_pipeline.py`). Ручной override (`PATCH /attempts/{aid}/answers/{ansid}`) ставит `manually_overridden=true` и атомарно пересчитывает `score/passed` в одной транзакции через `aggregate_score` — формула одна и та же для LLM-фазы и для override’а.
- **Очередь `quiz` отдельным воркером** (`celery_quiz`, concurrency=2). LLM-bound задачи теста не должны делить очередь с `vision` (где живёт длинный анализ слайдов), иначе генерация теста ждёт vision-jobs впереди. `quiz` зарезервирован под все Quiz-LLM-операции.
- **Anti-hallucination guard** в системном промпте `_QUIZ_GENERATE_V2_SYSTEM` — явный запрет придумывать ГОСТы, номера, обозначения, отсутствующие в материале. LLM возвращает структурированный JSON-объект, валидируемый через `_parse_payload_v2` с retry-on-malformed (single retry, по образцу `_chat_json_validated`).
- **`multiple_choice` — Jaccard с `max(0, …)` guard.** Объединение / пересечение множеств; отрицательного балла никогда не будет, даже при намеренно сломанном входе. Альтернатива — «−1 за лишний выбор» (academic standard для negative marking) — отложена до фактического запроса от преподавателей.
- **passed → `lesson_progress.is_completed`** через политику best-attempt: `quiz_score = max(существующий, новый)`, повторная неудачная попытка не регрессит уже сданный урок. Старое поле `lesson_progress.quiz_score:float` оставлено как есть (legacy, не удаляется — KNOWN_PROBLEMS).

**Альтернативы:**

- *Таблица на каждый тип вопроса* — 8 миграций, 8 join’ов при загрузке снапшота, неудобная сериализация в JSONB-снапшот всё равно потребовалась бы.
- *Snapshot ссылками на live-вопросы* — см. выше; для текущего workflow ломает либо UX (запрет редактирования), либо целостность (dangling).
- *Полностью LLM-grading (включая закрытые)* — медленно, дорого, недетерминированно; для single_choice/true_false это бессмысленно.
- *MongoDB для JSONB-payload* — добавление новой БД нарушает принцип «только Postgres + Redis», который зафиксирован для этого проекта.

**Trade-offs:**

- + Один источник правды (snapshot), безопасное редактирование, мгновенный фидбек по закрытым, точечный override по открытым.
- + Расширение типов = новая Pydantic-модель + ветка в `grading_service`. Никаких миграций БД.
- − При росте числа открытых вопросов в одной попытке Celery `prefork c=2` недоиспользует LLM-bound воркер (см. KNOWN_PROBLEMS).
- − Перегенерация в момент чужой in-progress попытки разрешена и зафиксирована как корректное поведение — преподаватель должен помнить об этом при «срочных» правках.
- − Per-question regenerate пока работает только для single_choice. Расширение на multi/open — отдельная задача.

---

## 33. Versioned quiz_questions + pointer-snapshots вместо full-snapshot

**Контекст:** Решение №32 фиксировало полный payload каждого вопроса в `quiz_attempts.questions_snapshot` (full snapshot). По мере роста попыток это давало: (а) дублирование ~500 байт на каждую попытку × каждый вопрос даже если эталон не менялся; (б) расхождение между «как выглядит вопрос в редакторе» и «как он был в попытке» приходилось разруливать сериализатором, а не схемой данных; (в) regenerate/edit нельзя было откатить — старый payload жил только внутри попыток.

**Решение:**

- `quiz_questions` становится **write-once + versioned**: композитный PK `(id, version)`, колонка `superseded_at timestamptz`, partial index `WHERE superseded_at IS NULL`. Любое изменение `payload`/`weight`/`type` делает INSERT строки `(id, version+1)` и UPDATE `superseded_at=now()` на старой — оба write’а в одной транзакции (`services/quiz_service.supersede_with_new_version`).
- `Quiz.questions` — view-only ORM-relationship по `superseded_at IS NULL`, чтобы редактор видел только текущие версии.
- Reorder/soft-delete мутируют **текущую** строку в place: `order` — атрибут видимой строки и не часть payload-инварианта (попытка всё равно фиксирует order у себя), а `delete` = ставит `superseded_at` без вставки наследника.
- `QuizAttempt.questions_snapshot` теперь — лёгкий pointer-снимок: `{"version": 1, "pointers": [{"question_id", "version", "order"}, ...]}`. Payload не копируется: грейдинг резолвит указатели в `quiz_questions` по `(id, version) IN VALUES (...)` одним SELECT через `services/quiz_service.resolve_snapshot[_sync]`, возвращая `list[ResolvedQuestion]`.
- `grade_question(type, payload, response)` не меняется по сигнатуре — меняется только источник payload (теперь `ResolvedQuestion.payload`, а не `snap[qid]["payload"]`). За счёт этого тот же закрытый алгоритм оценки сохраняет идентичные числа.

**Альтернативы:**

- *Оставить full-snapshot* (решение №32) — самый простой инвариант, но без возможности откатить regenerate и с быстрым ростом storage.
- *DB-side VIEW `quiz_questions_current`* поверх `WHERE superseded_at IS NULL` вместо ORM-relationship — кажется чище, но добавляет миграцию, которую SQLAlchemy autogenerate не видит, и заставляет руками поддерживать VIEW при изменении колонок. ORM-relationship с partial-index покрывает тот же hot path.
- *Хранить старые версии в отдельной таблице `quiz_questions_history`* — теряем компактный SELECT по `(id, version)` для grading_service, удваиваем insert-on-write.

**Trade-offs:**

- + Снимок попытки в ~10× меньше; storage на масштабе тысяч попыток существенно дешевле.
- + Полная история правок остаётся в одной таблице; диф «v3 vs v4» — SELECT в одну таблицу.
- + Битый указатель (несуществующая `(id, version)`) — явная `BrokenSnapshotError → HTTP 500`, не молчаливый None в скоринге.
- − Историческое раздувание таблицы при частой перегенерации; GC старых версий не входит в это решение и зафиксирован в KNOWN_PROBLEMS.
- − Миграция со старого «full snapshot» формата на pointers для уже существующих attempts не делается автоматически — старые in-progress попытки могут оказаться битыми. Триггер миграции и обработка legacy-снимков — в KNOWN_PROBLEMS.

---

## Связанные документы

- [ARCHITECTURE.md](ARCHITECTURE.md) — где эти решения видны в общей картине.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — последствия некоторых решений (особенно 4, 5, 8, 9).
- [DATA_FLOW.md](DATA_FLOW.md) — как эти решения работают вместе в конкретных сценариях.
