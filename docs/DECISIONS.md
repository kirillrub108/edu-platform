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
31. [AI-генерация и редактирование тестов](#31-ai-генерация-и-редактирование-тестов-quiz-authoring)
32. [Полноценный модуль тестирования: polymorphic JSONB + snapshot + hybrid grading](#32-полноценный-модуль-тестирования-polymorphic-jsonb--snapshot--hybrid-grading)
33. [Versioned quiz_questions + pointer-snapshots](#33-versioned-quiz_questions--pointer-snapshots-вместо-full-snapshot)
34. [Публикация: независимые флаги + read-time AND-видимость](#34-публикация-независимые-флаги--read-time-and-видимость)
35. [LessonVideo: версии вместо перезаписи](#35-lessonvideo-версии-вместо-перезаписи)
36. [Задания: вложения только хранятся + ретеншн](#36-задания-вложения-только-хранятся--ретеншн)
37. [Прод-стек: self-contained compose, миграции отдельным шагом, backup-сайдкар](#37-прод-стек-self-contained-compose-миграции-отдельным-шагом-backup-сайдкар)
38. [Сокращение TTL подписанных URL + 403-resilience плеера](#38-сокращение-ttl-подписанных-url--403-resilience-плеера-known_problems-14-partial)
39. [Хардненинг ЮKassa-вебхука: IP-allowlist + асинхронное начисление в Celery](#39-хардненинг-юkassa-вебхука-ip-allowlist--асинхронное-начисление-в-celery)
40. [Reconcile «зависших» платежей + единый путь расчёта](#40-reconcile-зависших-платежей--единый-путь-расчёта)
41. [Отдача видео: авторизованный `/stream` вместо signed-URL](#41-отдача-видео-авторизованный-stream-x-accel--presigned-вместо-signed-url-known_problems-34)
42. [Пустой ответ vision-модели — явная ошибка, а не тихий fallback](#42-пустой-ответ-vision-модели--явная-ошибка-а-не-тихий-fallback)
43. [SpeechKit v3: остаёмся на `containerAudio`](#43-speechkit-v3-остаёмся-на-containeraudio--22050-гц-это-нативная-частота-голосов-2026-08-16)
44. [`access_code` курса: генерируется сразу при создании, но остаётся nullable](#44-access_code-курса-генерируется-сразу-при-создании-но-остаётся-nullable)
45. [Переход LLM/Vision/TTS на Yandex AI Studio + SpeechKit v3](#45-переход-llmvisiontts-на-yandex-ai-studio--speechkit-v3-2026-08-12)
46. [Автодеплой: сборка образов на сервере по SSH, а не registry + pull](#46-автодеплой-сборка-образов-на-сервере-по-ssh-а-не-registry--pull-2026-08-14)
47. [База знаний урока: `LessonMaterial` + `LessonNote` в одном роутере](#47-база-знаний-урока-lessonmaterial--lessonnote-в-одном-роутере-2026-08-19)
48. [Метеринг AI-проверки и платное продление хранения — один кредитный леджер](#48-метеринг-ai-проверки-и-платное-продление-хранения--один-кредитный-леджер-2026-08-19)
49. [`POST /quiz/ai-review` — убран из-под кредитов, всегда бесплатен](#49-post-quizai-review--убран-из-под-кредитов-всегда-бесплатен-2026-08-20)
50. [Загрузки (`uploads.py`) переведены на `require_teacher`](#50-загрузки-uploadspy-переведены-с-require_verified_teacher-на-require_teacher-2026-08-20)
51. [Архив курса не отзывает доступ у записанного студента](#51-архив-курса-не-отзывает-доступ-у-записанного-студента-purge-пропускает-курсы-с-записями-2026-08-21)
52. [Мобильная навигация: один бургер в `AppHeader` + композабл состояния](#52-мобильная-навигация-один-бургер-в-appheader--композабл-состояния-2026-08-24)
55. [PPTX pre-processing: расширение `wrap="none"` боксов перед LibreOffice](#55-pptx-pre-processing-расширение-wrapnone-боксов-перед-libreoffice-2026-08-26)
56. [Шрифтопак в образе + телеметрия недостающих шрифтов](#56-шрифтопак-в-образе--телеметрия-недостающих-шрифтов-2026-08-26)

> Между §33 и §34 в теле идут несколько именованных (без номера) ADR — soft-delete, email-верификация,
> раздача `/files/*` через nginx, приоритет Celery по тарифу, монетизация/ЮКасса. Они актуальны.

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

> ⚠️ **Устарело (историческая запись).** Активный хешер теперь — **Argon2id** (`argon2-cffi`), bcrypt
> и sha256-обёртка удалены; password-shucking больше неактуален. Источник истины — [AUTH_FLOW.md](AUTH_FLOW.md) §2.

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

> ⚠️ **Устарело (историческая запись).** `/files/*` больше не публичный `StaticFiles`: байты отдаются
> через кастомный `files`-роутер с **HMAC-подписанными URL** (`signed_url_service.py`), а в проде —
> через nginx + `auth_request`. См. актуальную ADR «Раздача `/files/*` через nginx + `auth_request`» ниже.

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
- **Yandex SpeechKit** — качественнее, но платный. На момент этого решения поддержка была заглушена в коде (`raise NotImplementedError` в `tts_service.py`); с 2026-08-12 реализована полностью через SpeechKit v3 и стала прод-дефолтом — см. §45.
- **gTTS (Google Text-to-Speech)** — работает, но требует интернет на каждый запрос.
- **eSpeak** — звучит роботизированно, не подходит для educational.

**Trade-offs:**
- + Изолированная зависимость, не утяжеляет backend.
- + Можно скейлить отдельно от backend.
- + Бесплатно для **некоммерческого** использования (русские модели — CC-BY-NC 4.0); для коммерции нужна Silero EE (hello@silero.ai) или лицензированный TTS-провайдер (Polza / Yandex SpeechKit). См. [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).
- − Ещё один контейнер.
- − HTTP overhead на каждый запрос (vs прямой Python-вызов).

> **Обновление (2026-08-12).** Сам контейнер `silero-tts` убран из `docker-compose.yml`/
> `docker-compose.prod.yml` (см. §45) — код провайдера `TTS_PROVIDER=silero` остался и работает
> (`tts_service._synthesize_silero`), но требует теперь ручного self-host. Прод переключён на
> `TTS_PROVIDER=yandex`. `silero/config.py` в репозитории стал мёртвым кодом — раньше это был
> конфиг смонтированного контейнера, теперь его никто не монтирует (см. [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md)).

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

> ⚠️ **Устарело (историческая запись).** Канонический слой состояния теперь — **Pinia** (`stores/auth.ts`,
> `billing`, `comments`, `student`, `studentCabinet`, `assignments`). `useState`-синглтоны не используются
> для нового shared-состояния; `useCreationMode.ts` остался модулем констант. См. [ARCHITECTURE.md](ARCHITECTURE.md) §8.9.

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

> ⚠️ **Частично устарело.** Прогресс долгих задач теперь стримится по **SSE**
> (`sse-starlette`, `routers/lessons.py:progress_stream`, `composables/useProgressStream.ts`); поллинг
> `/task-status/{id}` оставлен как fallback. Запись ниже — историческая аргументация чистого polling.

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

## Soft delete: глобальный фильтр для User/Lesson, явный — для Course

**Контекст:** нужно архивирование курсов (teacher видит архив, студент — нет, физическое удаление через 30 дней) и «полное скрытие» для User/Lesson.

**Решение:**

- Колонка `deleted_at: DateTime?(indexed)` на `users`, `courses`, `lessons`.
- User и Lesson скрываются глобально: слушатель `do_orm_execute` на `Session` (под AsyncSession) добавляет `with_loader_criteria(deleted_at IS NULL)` ко всем ORM-SELECT (см. `app/database.py`).
- Course **намеренно НЕ** в фильтре — иначе teacher не увидел бы архив. Явные `Course.deleted_at.is_(None)` в `routers/students.py` стоят только на путях **discovery/enroll** (`/courses/preview`, `/enroll`); доступ уже записанного студента архивом не режется — см. §51.
- `DELETE /courses/{id}` = soft delete (204), `PATCH /courses/{id}/restore` = сброс. `GET /courses/grouped` отдаёт `{published, drafts, archived}` (отдельный эндпоинт, т.к. форма ответа отличается от `list[CourseOut]` и `response_model` фиксирован на маршрут).
- Физическое удаление + чистка файлов — задача `purge_soft_deleted` (очередь `quiz`, beat раз в сутки), sync-сессия с `execution_options(include_deleted=True)` для обхода фильтра.

**Альтернативы:**

- *Фильтр и для Course* — ломает teacher-архив; пришлось бы повсюду пробрасывать «show deleted».
- *`?grouped=true` к `GET /courses/`* — один маршрут с двумя формами ответа неудобен для `response_model`/OpenAPI.
- *Хард-delete как раньше* — нет восстановления и «передумал».

**Trade-offs:**

- + Скрытие User/Lesson — в одном месте, не размазано по роутерам.
- − `Session.get()` фильтр не перехватывает → `db.get(User/Lesson)` заменены на `select().where()`.
- − Soft-deleted teacher с живыми курсами: `Course.owner` грузится как `None` до purge (см. KNOWN_PROBLEMS).
- − Эмбеддед beat (`--beat` на celery_quiz) — допустимо для одного инстанса, не для кластера.

---

## Email-верификация и отправка писем

**Контекст:** при регистрации нужно подтверждать email, а после публикации видеолекции — уведомлять преподавателя. Письма не должны блокировать запросы или конкурировать с генерацией видео за concurrency.

**Решение:**

- **Stateless verify-токен** через `itsdangerous.URLSafeTimedSerializer` (подпись на `SECRET_KEY`, salt `email-verify`, срок `EMAIL_VERIFICATION_TTL_SECONDS`). Токен — сам по себе доказательство, **таблицы в БД нет** (`generate_/verify_email_verification_token` в `services/auth_service.py`).
- **Отдельная очередь `celery_email`** и воркер `celery_email_worker` (`-Q celery_email -c 2`). Таска `send_email` (`app/tasks/email_pipeline.py`) — sync, `autoretry_for=(EmailDeliveryError,)` (сеть/5xx), `max_retries=3`, exp backoff; провайдерский 4xx — постоянная ошибка (`RuntimeError`, без ретраев).
- **Тонкий `email_service`**: Jinja2-рендер (`templates/email/*.html`) + sync-отправка через провайдер, выбираемый по `EMAIL_PROVIDER` (реализован Resend по HTTP, интерфейс готов под SendGrid). Web-сторона провайдера НЕ дёргает — только ставит `send_email.delay(...)`.
- **Гейтинг, а не блок логина:** `require_verified_teacher` (переиспользует `require_teacher`) навешен только на эндпоинты создания/изменения контента (courses POST/PUT, modules, lessons POST + generate-video, uploads/\*, slides analyze). Неверифицированный teacher логинится и читает данные, но контент не создаёт → 403.
- `video_pipeline` после `_set_status(published)` ставит письмо «видео готово»; сбой постановки обёрнут и не роняет статус.

**Альтернативы:**

- *Токен в БД (one-time)* — даёт отзыв и одноразовость, но требует таблицу + чистку; для подтверждения email избыточно, подписанного TTL-токена достаточно.
- *Блокировать логин до верификации* — хуже UX (юзер не может зайти и переотправить письмо), ломает resend-флоу.
- *Слать письма из очереди video/vision* — отнимает concurrency у тяжёлой генерации; отдельная очередь изолирует.

**Trade-offs:**

- + Подтверждение email не трогает access-путь и не требует БД-состояния.
- + Падение почтового провайдера ретраится и не влияет ни на регистрацию, ни на published-статус.
- − Stateless-токен нельзя отозвать досрочно (живёт весь TTL); приемлемо для verify.
- − `EMAIL_VERIFICATION_TTL_SECONDS`/retry — в `constants.py`, секреты (`RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL`) — в `config.py`/`.env`.

---

## Одноразовость verify-токена, гейтинг AI и подтверждение почты на фронте

**Контекст:** базовый email-verify уже был (stateless `itsdangerous`-токен, Resend, `require_verified_teacher` на контент-эндпоинтах). Требовалось: гарантировать одноразовость ссылки, загейтить **весь** AI-функционал, и довести фичу до фронта (плашка + модалка + страница `/verify-email`).

**Решение:**

- **Одноразовость поверх stateless-токена.** Сам подписанный токен не меняли (старый GET-путь и его тесты живы). Новый `services/email_token_service.py` (`issue`/`consume`) при успешном `consume` атомарно помечает токен израсходованным в Redis: `email_verify_used:<sha256(token)>` через `SET NX` (TTL = срок токена). Повтор того же токена → `TokenError("used")` → 400. Переиспользуется общий async-Redis проекта.
- **POST `/auth/verify-email {token}` для SPA** (рядом со старым GET-redirect, который оставлен как fallback). Письмо теперь ведёт на `FRONTEND_URL/verify-email?token=…` → страница дёргает POST. Идемпотентно для уже подтверждённого аккаунта со свежим токеном; 400 на битый/истёкший/использованный.
- **Resend-cooldown.** `email_verify_cooldown:<user_id>` (TTL `EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS=60`) поверх slowapi-лимита → 429 при спаме.
- **`require_verified_email`** (поверх `get_current_user`, role-agnostic, `detail="email_not_verified"`) навешен на ранее НЕзагейченные AI-эндпоинты: slide regenerate, quiz generate / question regenerate / ai-review. `require_verified_teacher` на analyze/generate-video оставлен как был. Гейт-тест принимает обе зависимости.
- **Реестр + страж.** `AI_GATED_ENDPOINTS` в `dependencies.py` — источник истины. `tests/integration/test_ai_gating_guard.py`: (1) каждый эндпоинт реестра реально зависит от verify-гейта; (2) каждый роут, ставящий Celery-таску (кроме infra `send_email` и студенческого `grade_attempt_task`), обязан быть в реестре. Новый незагейченный AI-эндпоинт → тест падает.
- **Dev без почты:** `send_email_sync` при пустом `RESEND_API_KEY` логирует письмо (со ссылкой в контексте) и не падает.
- **Фронт:** `is_email_verified` в auth-store (Pinia) + состояние модалки; `useAiGuard().ensureVerified(action)` оборачивает все AI-кнопки (generate-video, analyze, slide regenerate, quiz generate/regenerate/ai-review) — при неверифицированной почте запрос на бэк не уходит, открывается `VerifyEmailModal` (смонтирована один раз в `app.vue`). Плашка в `AppHeader`, страница `pages/verify-email.vue`.

**Альтернативы:**

- *Полностью opaque Redis-токен (как в типовом дизайне)* — переписывал бы рабочий stateless-токен и его тесты; sha256-нонс даёт одноразовость без этого.
- *Студенческий `grade_attempt` тоже под гейт* — ломает прохождение тестов неверифицированным студентам без фронтового аналога модалки; явно исключён в страже.
- *Общий суб-роутер `Depends(require_verified_email)`* — слишком инвазивно (AI-эндпоинты размазаны по 3 роутерам с разными зависимостями); выбран явный реестр + страж.

**Trade-offs:**

- + Одноразовость и cooldown без БД-состояния и без нового Redis-пула.
- + Любой новый AI-эндпоинт ловится стражем (для Celery — автоматически).
- − Синхронные AI-эндпоинты (без Celery) страж автоматически не находит — держатся реестром вручную (для них работает проверка №1).
- − Сосуществуют два verify-гейта (`_teacher` / `_email`); намеренно, чтобы не трогать рабочие эндпоинты и их сообщения.

---

## Раздача `/files/*` через nginx + `auth_request` (не `secure_link`)

**Контекст.** В prod статику (PPTX/PNG/MP4) нужно отдавать напрямую с диска (sendfile) и кешировать на CDN, а не гонять через FastAPI StaticFiles. Подписанные URL остаются обязательными.

**Решение.** nginx (`nginx/default.conf`) отдаёт `/files/*` через `alias` из `./backend/storage` (`:ro`), а подпись проверяет `auth_request` → внутренний эндпоинт бэка `GET /internal/files/verify` (`routers/files.py:internal_router`), который переиспользует `verify_signed_url` без изменений. Эндпоинт возвращает остаток жизни подписи в `X-Signed-TTL`; nginx через `auth_request_set` превращает его в `Cache-Control: max-age=<ttl>`, так что CDN не кеширует файл дольше валидности подписи.

**Почему не `secure_link`.** Модуль `ngx_http_secure_link_module` умеет только plain **MD5 (base64url)**. Текущая подпись — **HMAC-SHA256/hex**. Совместимость потребовала бы даунгрейда до неусиленного MD5 (уязвим к length-extension) и дублирования/переписывания логики подписи. `auth_request` сохраняет HMAC-SHA256 и переиспользует сервис как есть; цена — хит в origin на cache-miss (на cache-hit CDN отдаёт сам).

**dev vs prod.** Флаг `SERVE_STATIC_VIA_NGINX` (`config.py`): `false` (dev) — FastAPI регистрирует `files.router` и отдаёт `/files/*` сам, nginx простаивает на `:8080`; `true` (prod) — регистрируется только `files.internal_router`, файлы отдаёт nginx. Публичный домен ссылок — `PUBLIC_FILES_BASE_URL` (пусто → `BASE_URL`).

---

## Приоритет Celery-задач по тарифу

**Контекст.** Платные пользователи должны получать приоритет на постановке дорогих AI-задач (видео, vision). Лимитирование трат — отдельная история: им рулят **кредиты** (`billing_service`), отдельных квот/лимита одновременных джобов нет.

**Решение.**
- **Tier выводится из биллингового `CreditAccount.plan`**, отдельной колонки нет (`PLAN_TIER_MAP` в `constants.py`: free→free, starter/pro/school→paid). Один источник истины «плана», без второй сущности. `enterprise` — задел: наивысший приоритет, но ни один текущий план в него не маппится (без отдельной логики/UI). Промоут школьного плана в enterprise — одна строка в `PLAN_TIER_MAP`.
- **Приоритет — `apply_async(priority=TIER_PRIORITY[tier])`** с сохранением маршрутизации (`queue="video"/"vision"`), а не отдельные очереди на тариф (иначе воркеры/маршрутизация дублируются на каждый тариф). В Redis-брокере **меньшее число = выше приоритет** (0 берётся первым, 9 последним — обратно RabbitMQ; сверено с доками Celery). Поэтому `enterprise=0, paid=3, free=9`. В `celery_app.py`: `broker_transport_options={priority_steps: 0..9, sep: ":", queue_order_strategy: "priority"}` + `worker_prefetch_multiplier=1` (иначе prefork-воркер префетчит низкоприоритетную задачу раньше и приоритет не работает).
- Резолв приоритета — `services/tier_service.priority_for_user(db, user_id)` (async); роутеры `generate-video`/`analyze` остаются тонкими (один вызов + проброс `priority` в `apply_async`). Логика трат (резерв/charge кредитов) — без изменений.

**Trade-offs:**

- + Один источник «плана» (CreditPlan); приоритет без дублирования очередей; лимиты целиком на кредитах.
- − `school` и `starter` пока в одном tier (paid): три tier'а на четыре плана; enterprise зарезервирован под будущее.
- − `worker_prefetch_multiplier=1` чуть снижает throughput на мелких задачах ради корректного приоритета (видео/vision долгие — некритично).

---

## Монетизация: формульный прайс, резерв в роутере, кооперативная отмена, ЮКасса

**Контекст.** Кредиты были плоскими (`CREDIT_WEIGHTS["lesson_generate"]=10`), резерв жил внутри Celery-таски (TOCTOU-окно после проверки баланса в роутере), отмена убивала таску `revoke(terminate=True)`, покупки кредитов не было.

**Решение.**
- **Двухслойная модель цены.** Пользователю — детерминированная формула (`billing_service.estimate_video_text/auto`: база + слайды + `ceil(символы/3000)`; компоненты в `constants.py`). Факт провайдерских трат — в `generation_usage` (хуки в `llm_service`/`vision_analysis`/`tts_service` на месте реальных HTTP-вызовов; кеш-хиты не журналируются). Метрика `ai_cost_rub` — DB-backed коллектор на FastAPI-стороне, т.к. Prometheus скрейпит только backend, не воркеры.
- **Резерв полного эстимейта — в роутере до `apply_async`** (порядок: concurrency → estimate → триал/резерв → enqueue), с уникальным `billing_ref` на запуск. Таска только **финализирует**: `sync_finalize_generation` в одной транзакции списывает spent и возвращает остаток, идемпотентно по леджеру (повторный finalizer для `billing_ref` — no-op; переживает Celery-redelivery при `acks_late`). Старые `sync_reserve/charge/release_credits` удалены.
- **Гонка «cancel-эндпоинт vs финализация таски»** решается claim'ом: `lesson.billed_via` обнуляется под `FOR UPDATE` (`claim_billing`/`sync_claim_billing`) — ровно одна сторона выполняет возврат/списание (критично для триал-слотов, у которых нет леджера).
- **Кооперативная отмена** (`POST /lessons/{id}/cancel-generation`): таска в очереди (PENDING) → `revoke()` без terminate + полный возврат; бегущая — флаг `cancel_requested`, пайплайны проверяют его на границах слайдов (video: тела циклов `as_completed` + старт `_do_tts`; vision: `cancel_check` в `analyze_presentation`), списывают `база + слайды + ceil(озвучено/3000)` (vision — pro-rata), остаток возвращают, статус → `cancelled`. SIGKILL больше не используется; старые `cancel-video`/`analysis-cancel` — делегаты.
- **Lifetime-триал free-аккаунтов** (`usage_counters`, `period_key='lifetime'`): 2 лекции + 2 теста вместо кредитов (атомарный UPSERT `...DO UPDATE WHERE count < :limit RETURNING`); кап лекции ≤20 слайдов и ≤15000 символов. Welcome-кредиты free-плана убраны (50→0) — иначе «3-я лекция → 402 trial_exhausted» недостижим. Vision-анализ под неисчерпанным триалом бесплатен и слот не жжёт — слот сжигает только generate-video (успех или отмена после ≥1 слайда; фейл сервиса возвращает слот).
- **ЮКасса без SDK** (httpx, `services/yookassa_service.py`): `POST /billing/payments` (Idempotence-Key = `Payment.idempotence_key`, redirect-confirmation, чек 54-ФЗ за флагом `YOOKASSA_SEND_RECEIPT`), webhook `POST /billing/webhooks/yookassa` телу не доверяет — re-fetch платежа из API; начисление `apply_purchase` идемпотентно (лок строки Payment → лок счёта, один порядок локов с поллингом). `GET /billing/payments/{id}` тоже финализирует — локальный флоу работает без публичного webhook. Webhook вне CSRF автоматически: у него нет cookie-зависимостей (список исключений не нужен — его не существует).
- **Деплой-нота:** задачи, поставленные в очередь до деплоя, не несут биллинг-полей урока — выполняются как unbilled (warning в логах). Очереди дренировать перед деплоем (тот же прецедент, что миграция очередей в KNOWN_PROBLEMS).

**Trade-offs:**

- + Списание ровно эстимейт / полный возврат / частичное при отмене — атомарно и идемпотентно; покупка не дублируется при повторной доставке webhook.
- − Цена авто-режима — норматив 600 симв/слайд, а не факт (предсказуемость до анализа дороже точности).
- − Слайды PDF до рендера считаются эвристикой по байтам (`/Count`); экзотические PDF с object streams могут не посчитаться → 422 до запуска.
- − Триал-слот квиза при двойном фейле с redelivery теоретически может вернуться дважды (клемп ≥0; у слотов нет леджера) — принято как редкий и дешёвый кейс.

---

## 34. Публикация: независимые флаги + read-time AND-видимость

**Контекст.** Преподаватель готовит курс по частям и должен показывать студентам только то, что готово, на трёх уровнях: курс → модуль → урок. Нужна предсказуемая семантика «снял с публикации / вернул».

**Решение** (`services/visibility_service.py`):
- **Три независимых булевых флага** `is_published` — на `Course`, `Module`, `Lesson`. Каждый переключается своим эндпоинтом: курс — `PUT /courses/{id}/publish` (toggle); модуль — `POST /courses/{cid}/modules/{mid}/publish|unpublish`; урок — `POST /lessons/{id}/publish|unpublish` (set true/false, идемпотентно).
- **Видимость записанного студента = `module.is_published AND lesson.is_published`**, вычисляется в read-time (`lesson_visible_to_student`). Единственный источник истины; вызывается из `require_lesson_access` и `visible_module_tree`.
- **`course.is_published` намеренно исключён из правила видимости.** Он гейтит только *обнаружение курса в каталоге* и *новую запись* (`enroll`, `students/courses/preview`), а не доступ уже записанного студента. Итог расцепления: снял курс с публикации → курс ушёл из каталога и новые записаться не могут, **но записанные сохраняют доступ** к `module/lesson`-published урокам (в т.ч. пройденным). Чтобы спрятать материалы у всех — снимают с публикации модуль/урок (контент-гейт сохранён).
- **Unpublish ≠ архив.** Unpublish — обратимое «скрыть из каталога», доступ записанных сохраняется. Архив (`Course.deleted_at`, `DELETE /courses/{id}` → restore/`purge_pipeline` через `SOFT_DELETE_PURGE_DAYS`) — отдельный, более жёсткий гейт, ведущий к удалению; ретеншн на unpublish НЕ распространяется.
- **Снятие публикации родителя НЕ трогает флаги детей** — скрытие чисто read-time-эффект AND. Опубликовал родителя обратно → потомки сразу видны (их флаги не сбрасывались).
- Черновик модуля/урока → студенту **404, а не 403** (не раскрываем существование неопубликованного). 403 — только «не записан на курс».
- Перед снятием курса с публикации фронт предупреждает, когда есть записанные (`enrollment_count > 0` в `CourseDetail`, считается подзапросом в `GET /courses/{id}` без новой колонки): записанные сохранят доступ, новые — нет.

**Альтернативы:**
- *Каскадный флаг (unpublish курса → false у всех уроков)* — теряется состояние «что было опубликовано», повторная публикация требует заново пройтись по детям.
- *Один флаг на урок без цепочки* — нельзя спрятать целый модуль/курс одним действием.

**Trade-offs:**
- + Гибкая ре-публикация, одно правило видимости, нет рассинхрона флагов.
- − Видимость нельзя прочитать из одного поля — нужно тянуть всю цепочку (делается через `joinedload` в `require_lesson_access`).

---

## 35. LessonVideo: версии вместо перезаписи

**Контекст.** Раньше у урока был один `video_url`; повторная генерация затирала предыдущий результат — нельзя было сравнить варианты и выбрать лучший перед показом студентам.

**Решение** (`models/lesson_video.py`, коммит «latest video preview + publishing options»):
- Отдельная таблица **`lesson_videos`** (`lesson_id`, `video_url`, `voice`, `creation_mode`, `is_published`, `created_at`). Каждая успешная генерация (и прямая загрузка) добавляет строку с `is_published=False` (`tasks/video_pipeline.py`).
- `GET /lessons/{id}/videos` — список версий (новые сверху). `POST /lessons/{id}/videos/{video_id}/publish` помечает одну `is_published=True`, **снимает остальные** (`UPDATE … SET is_published=False`) и синхронит `lesson.video_url = video.video_url`, чтобы плеер студента продолжал работать без доп. запроса. Идемпотентно.
- `LessonOut.published_video` отдаёт текущую опубликованную версию при чтении урока.
- Прямая загрузка готового видео (`/upload-video`) сразу `is_published=True`.

**Альтернативы:**
- *Хранить только последнее видео в `lesson.video_url`* — нет превью/отката, гонка «генерю новое, студент смотрит старое».
- *Версии как файлы без таблицы* — нет метаданных (voice/mode/время) и атомарного выбора активной версии.

**Trade-offs:**
- + Превью нескольких вариантов, явный выбор активной версии, откат.
- − Старые неопубликованные версии копятся в storage (чистятся `purge_pipeline` вместе с уроком; отдельного GC версий нет).

---

## 36. Задания: вложения только хранятся + ретеншн

**Контекст.** Студенты сдают задания текстом и/или файлами (вплоть до видео); нужны оценка, приватный тред с преподавателем и защита от вредоносных загрузок без раздувания хранилища.

**Решение** (`models/assignment.py`, `services/assignment_service.py`, `file_validation_service.py`):
- **Вложения только СОХРАНЯЮТСЯ, не парсятся** на сервере — это снимает классы XXE/zip-bomb из office-файлов. Допуск — whitelist расширение→MIME-категория (`ATTACHMENT_ALLOWED_TYPES`/`ATTACHMENT_EXTENSION_MIME` в `constants.py`) + проверка magic-байтов/zip-slip в `file_validation_service`; лимиты — per-category размер, число файлов (`ATTACHMENT_MAX_FILES`), суммарный размер сабмишна. Стрим в storage обрывается при превышении hard-cap.
- **Один сабмишн на пару `(enrollment, assignment)`** (UNIQUE, race-safe `get_or_create`); статусы `draft → submitted → returned`, оценка/фидбек скрыты от студента до `returned`. Оценка нормируется в 0..1 через общий `grading_service.aggregate_score` (та же формула, что в квизах), при `pass_threshold` — отметка урока пройденным.
- **Приватный тред** (`AssignmentMessage`) — обе стороны, лимит 30/мин; студент видит только свой сабмишн.
- **Ретеншн:** строки-оценки хранятся как аудит, а **файлы** вложений авто-удаляются через `ATTACHMENT_RETENTION_DAYS_AFTER_GRADED` после `graded_at` (`purge_pipeline`), экономя storage.

**Альтернативы:**
- *Парсить/превьюшить office-вложения на сервере* — открывает XXE/zip-bomb; не нужно для сдачи.
- *Хранить файлы вечно* — линейный рост storage на видео-вложениях.

**Trade-offs:**
- + Безопасный аплоад без парсинга; единая формула оценки с квизами; storage не растёт бесконечно.
- − Перезалитый файл создаёт новую строку — старый лежит до purge; нет server-side превью содержимого.

---

## 37. Прод-стек: self-contained compose, миграции отдельным шагом, backup-сайдкар

**Контекст.** Dev `docker-compose.yml` заточен под удобство (bind-mounts кода, `--reload`, авто-миграции в lifespan). Для прода это небезопасно, но и плодить хрупкий `-f base -f override` не хотелось.

**Решение** (`docker-compose.prod.yml`):
- **Self-contained, НЕ override.** Запускать только как `-f docker-compose.prod.yml` — Compose **мёржит списки** (volumes/ports), поэтому наложение на dev-файл протащило бы dev bind-mount'ы кода. Код берётся только из собранных образов.
- **Миграции — отдельный one-shot сервис `migrate`** (`--profile migrate`, `alembic upgrade head`) до роллаута; в проде `RUN_MIGRATIONS_ON_STARTUP=false` (см. §7 / KNOWN_PROBLEMS §5.1). Упавшая миграция валит деплой, не трогая работающую версию.
- **gunicorn** (uvicorn-воркеры, без `--reload`) для backend, `frontend/Dockerfile.prod` (`nuxt build` → node-сервер), **nginx** отдаёт `/files/*` + TLS, `certbot`-профиль для сертификатов.
- **Backup БД — сайдкар `db_backup`** (постгрес-образ той же версии): цикл `pg_dump -Fc` → volume `db_backups`, ретенция `BACKUP_RETENTION_DAYS`; restore через `pg_restore` (DEPLOYMENT §7). Off-host копия в Object Storage — post-MVP.

**Альтернативы:**
- *`-f base -f prod` override* — тихий лик dev bind-mount'ов (Compose мёржит списки); поэтому self-contained.
- *Миграции в lifespan и в проде* — тяжёлая миграция роняет readiness, гонка реплик за advisory-lock.
- *Бэкап вручную/cron на хосте* — не воспроизводимо между окружениями; сайдкар везёт версию pg_dump вместе с БД.

**Trade-offs:**
- + Прод-конфиг воспроизводим и изолирован от dev; миграция — управляемый шаг деплоя; есть регулярный бэкап.
- − Дублирование части определений между dev и prod compose (плата за self-contained).
- − Single-instance backup на volume — не защищает от потери хоста до появления off-host копии.

---

## 38. Сокращение TTL подписанных URL + 403-resilience плеера (KNOWN_PROBLEMS 1.4, partial)

**Контекст.** `/files/*` раздаётся через HMAC-SHA256-подписанные URL (bearer-style: подпись в query-параметрах, без session-binding). Утёкшая ссылка валидна у любого до истечения TTL. Предыдущий дефолт — 3600 с.

**Решение:**
- **TTL сокращён**: дефолт `SIGNED_URL_EXPIRES_IN` снижен с 3600 до 1800 с. Добавлены per-content константы в `constants.py`: `SIGNED_URL_TTL_VIDEO = 1800` (видео, ≈ один просмотр), `SIGNED_URL_TTL_SLIDE = 600` (PNG слайдов, только на время редактирования). `storage_service.get_url` / `resign_url` принимают `expires_in`, роутеры явно передают нужный тип. `SIGNED_URL_EXPIRES_IN` остаётся в `config.py` как env-override-cap для некатегоризованных файлов.
- **403-resilience во фронтенде**: `LessonPlayer.vue` и `VideoGenerationPanel.vue` ловят `@error` на `<video>` и эмитят `video-url-expired` (once per URL, guard через `retried`-ref со сбросом по `watch`). Родительские страницы перезапрашивают урок/видеоисторию — получают свежую подпись без перезагрузки. Параллельные 403 не устраивают шторм re-fetch (один retry на URL-change).

**Что отклонено:**
- **Session-binding (привязка подписи к cookie-сессии)** — убивает CDN-кеш (каждый пользователь получает уникальный URL) и ломает bearer-загрузку медиа в `<video>` (без credentials). Deferred.
- **Per-request signed URLs (mint at request time, TTL = сcession)** — правильный путь для платного контента: URL виден только тому, кто сделал API-запрос. Сложнее стриминга (range-запросы в середине просмотра требуют re-mint). Deferred на этап платного контента.

**Влияние на CDN:** `X-Signed-TTL` → `Cache-Control: max-age` теперь ≤ 1800 с для видео. На cache-hit CDN отдаёт сам; на cache-miss — хит в origin. Для слайдов max-age = 600 с — чаще origin-хиты при редактировании, но слайды малы и быстро кешируются.

**Residual risk:** подпись по-прежнему bearer-style; окно эксплуатации сужено с 60 до 30 мин для видео. Принято как MVP trade-off — зафиксировано в [KNOWN_PROBLEMS.md §1.4](KNOWN_PROBLEMS.md#14--files-отдаётся-без-авторизации).

---

## 39. Хардненинг ЮKassa-вебхука: IP-allowlist + асинхронное начисление в Celery

**Контекст.** Базовая интеграция ЮKassa уже была (модель `Payment`, `yookassa_service`, роуты создания/поллинга/вебхука, идемпотентный `apply_purchase`). Вебхук, однако, начислял кредиты **inline** прямо в запросе (re-fetch + `apply_purchase`), не проверял источник и не сверял сумму.

**Решение:**
- **IP-allowlist (defence-in-depth).** `services/webhook_security.py`: реальный IP берётся из `X-Forwarded-For` **только** если непосредственный TCP-пир — доверенный прокси (`YOOKASSA_TRUSTED_PROXIES`: loopback/docker/nginx), иначе из `request.client`. IP сверяется с `YOOKASSA_TRUSTED_CIDRS` (переопределяемый fallback; источник истины — доки/SDK ЮKassa). Недоверенный IP → 400. Тумблер `YOOKASSA_VERIFY_WEBHOOK_IP`. Тело уведомления по-прежнему не считается достоверным — платёж перезапрашивается.
- **Начисление вынесено в синхронный Celery-таск** `process_yookassa_payment` (очередь `quiz`, приоритет `PAYMENT_TASK_PRIORITY=0`). Вебхук только валидирует IP, парсит событие и **сразу отдаёт 200** (останавливает 24-часовые ретраи). Таск: sync-клиент `get_payment_sync` (re-fetch) → `SELECT … FOR UPDATE` на sync-сессии → валидация → `sync_apply_purchase`. Граница async/sync соблюдена (в `app/tasks/*` только sync).
- **Анти-фрод сверка.** `payment_matches`: кредиты начисляются только если `status==succeeded ∧ paid ∧ currency==RUB ∧ amount == цене пакета`. Применяется и в таске, и в async-поллинге.
- **Гонка «вебхук раньше коммита `yookassa_payment_id`».** Таск находит локальный платёж по `metadata.payment_id` (наше значение, возвращённое авторитетным GET) → не зависит от того, успел ли закоммититься `yookassa_payment_id`. Фолбэк-поиск по `yookassa_payment_id`.
- **`require_verified_email`** на `POST /payments`; `metadata.user_id`; per-package `vat_code/payment_subject/payment_mode` в `CREDIT_PACKAGES`.

**Edge case — возврат (`refund.succeeded`).** Фиксируем факт: `Payment.refunded_at` проставляется один раз (`sync_mark_payment_refunded`). **Уже потраченные кредиты автоматически НЕ списываются** — это ручное/финансовое решение (баланс может уйти в минус, нужна политика). Отложено: автосписание/блокировка при возврате, сохранение карты и автоплатежи (v2).

**Trade-offs:**
- + Вебхук отвечает мгновенно и не висит на сетевом round-trip к ЮKassa; источник IP не подделать; сумма сверяется до начисления.
- − Две точки начисления (sync-таск для вебхука + async-инлайн для поллинга/локалки), обе идемпотентны через `Payment.status` под блокировкой.
- − IP-allowlist — статический fallback; при смене диапазонов ЮKassa нужно обновить `constants.py` (или включить SDK `SecurityHelper`).

---

## 40. Reconcile «зависших» платежей + единый путь расчёта

**Контекст.** Поскольку вебхук отвечает 200 сразу (§39), ЮKassa больше НЕ редоставляет уведомление. Появился тихий разрыв: вебхук вернул 200, но таск не поставился в очередь (Redis моргнул), а пользователь закрыл return-страницу → платёж навсегда висит в `pending`.

**Решение:**
- **Единый путь расчёта.** Денежная логика вынесена в `tasks/payment_pipeline._settle_payment(db, yk, event)` (locate FOR UPDATE → `payment_matches` → `sync_apply_purchase`/cancel/refund). Её РЕЮЗят и вебхук-таск `process_yookassa_payment`, и reconcile — копии нет.
- **Периодический backstop.** Синхронный beat-таск `reconcile_pending_payments` (в celery_quiz, очередь `quiz`, интервал `RECONCILE_INTERVAL_MINUTES`): выбирает `pending`-платежи в окне `[RECONCILE_MIN_AGE_MINUTES, RECONCILE_MAX_AGE_HOURS]`, делает авторитетный `get_payment_sync` и прогоняет через `_settle_payment`. Идемпотентность наследуется от guard'а по терминальному статусу под блокировкой — вебхук + reconcile никогда не зачислят дважды.
- **Алёрт «совсем зависших».** Платёж в `pending` дольше `PAYMENT_STUCK_ALERT_MINUTES` → структурированный лог ERROR (→ Sentry) и опциональное письмо админу (`PAYMENT_STUCK_ALERT_EMAIL` + `ALERT_ADMIN_EMAIL`), ровно один раз через `Payment.alerted_at` (`skip_locked`, без спама).
- **След для reconnect не добавлялся в вебхук:** durable-трейс зависшего платежа — это сама строка `Payment(status=pending)`, созданная на `create_payment` ДО любого вебхука; enqueue и так идёт строго после успешного парса. Отдельная таблица событий не нужна.

**Trade-offs:** + закрыт единственный путь к навсегда-зависшему оплаченному платежу; − лишний beat-таск и сетевые GET'ы раз в интервал (батч ограничен, окно по возрасту отсекает мёртвые). Порог reconcile 10 мин (дать вебхуку/поллингу успеть), потолок 72 ч (не дёргать мёртвые), алёрт 60 мин.

---

## 41. Отдача видео: авторизованный `/stream` (X-Accel / presigned) вместо signed-URL (KNOWN_PROBLEMS 3.4)

**Контекст.** [KNOWN_PROBLEMS §3.4](KNOWN_PROBLEMS.md) описывает Python-стриминг видео как нагрузку на backend-CPU. Но в проде байты `/files/*` уже раздаёт nginx через `auth_request` (см. «Раздача `/files/*` через nginx»), Python-стриминг остался только в dev — CPU-приз в проде фактически взят. Реальная цель — **увести видео на S3** и заодно усилить модель доступа. Раньше `lesson.video_url` / `LessonVideo.video_url` = bearer signed-URL (§38): enrollment/visibility проверялись в момент выдачи DTO (роуты урока), а сам `/files/*` — только HMAC-подпись, без пере-проверки записи на курс.

**Решение:**
- **Два авторизованных эндпоинта** в `routers/lessons.py` под `require_lesson_access` (правило видимости не инлайнится — берётся из `visibility_service`): `GET /{lesson_id}/video/stream` (текущее видео — источник плеера) и `GET /{lesson_id}/videos/{video_id}/stream` (конкретный рендер; владелец видит любой, записанный студент — только `is_published`, черновой рендер → 404, не палит существование).
- **Режим по `STORAGE_BACKEND`.** `s3` → `302` на короткоживущий presigned-URL (браузер стримит прямо из S3, range/seek держит S3). `local` + nginx → пустой ответ с `X-Accel-Redirect` на internal-локацию `/protected-media/` (alias на storage; nginx отдаёт с range/sendfile, абсолютный путь ФС клиенту не утекает). `local` без nginx (dev) → `302` на **подписанный абсолютный `/files/*` URL** (браузер грузит байты напрямую с backend). Флаги — только в `constants.py`: `VIDEO_XACCEL_ENABLED = settings.SERVE_STATIC_VIA_NGINX` (co-varies с наличием nginx), `VIDEO_XACCEL_INTERNAL_PREFIX`, `S3_PRESIGN_TTL_SECONDS`.
- **Выбор URL плеера — same-origin `/stream` в проде, bearer-`/files` в dev.** `video_playback_url` (в `_lesson_out` / `_video_out` / студенческом роуте) отдаёт **относительный** `/stream` в проде (nginx same-origin, кука едет сама → X-Accel/302) и **подписанный абсолютный `/files` URL** в dev. Почему dev особый: dev-фронт зовёт backend **cross-origin** (`NUXT_PUBLIC_API_BASE=http://localhost:8000/api/v1`, Nitro-devProxy не задействован), а SameSite-кука на cross-origin `<video>` не уходит → `/stream` там недостижим; bearer-`/files` грузится напрямую, как обложки. В проде `apiBase=/api/v1` (same-origin за nginx), поэтому относительный `/stream` работает.
- **Старый путь закрыт там, где это важно (prod).** `/files/videos/*` блокируется в **prod-verify** (`verify_file_signature`, регистрируется при `SERVE_STATIC_VIA_NGINX=true`) — nginx отдаёт `/files/*`, и видео-путь возвращает 403 даже с валидной подписью, так что единственный путь к байтам — `/stream` (X-Accel, live-check). В dev `serve_file` (единственный `/files`-роут без nginx) намеренно оставлен открытым как 302-цель. Письмо «видео готово» ссылается на страницу урока, не на файл, так что переходный период не нужен.

**Главный trade-off — доступ в S3-режиме = bearer-на-TTL.** Live per-request re-check (каждый range проходит `require_lesson_access`) есть только на local-X-Accel-пути. В S3-режиме после `302` браузер ходит **напрямую к S3** по presigned-URL, валидному весь TTL: **отписка/скрытие урока НЕ отзывают доступ мгновенно**, только по истечении. Принято осознанно — окно ограничено TTL. `S3_PRESIGN_TTL_SECONDS = 6h`: должен покрывать длину урока, т.к. `<video>` перезапрашивает range напрямую по этому URL — короткий TTL (напр. 300 с) порвал бы перемотку на длинной лекции. `Cache-Control: no-store` на `302`, чтобы presigned не осел в общем/CDN-кеше и не утёк между студентами; относительный `/stream` в сериализаторе → фронт кеширует стабильный путь, presigned свежий на каждый заход.

**Заметки:** на S3-таргете `/protected-media/` (local-X-Accel) — мёртвая ветка (видео физически не на диске ноды), но нужна для local-деплоя/dev-fallback. Эндпоинт не гейтится `require_verified_email` (воспроизведение — не AI-операция) и потому не входит в `AI_GATED_ENDPOINTS`. Схему `LessonVideo` и второй refresh-путь не трогали.

---

## 42. Пустой ответ vision-модели — явная ошибка, а не тихий fallback

**Контекст:** `VisionAnalysisService._call_ollama` может получить пустой `content` от модели (например, если reasoning-модель тратит весь `LLM_MAX_TOKENS` на скрытые рассуждения и ничего не оставляет на ответ). Нужно было решить, что делать с таким ответом на уровне одного HTTP-вызова к модели.

**Решение:** `_call_ollama` логирует `vision_empty_content` (ERROR) и кидает `RuntimeError` с подсказкой («set VISION_REASONING_EFFORT=none or raise LLM_MAX_TOKENS»), а не возвращает `""`. Сдерживание вынесено на уровень выше, отдельно для каждого потребителя:
- `analyze_presentation` (per-slide, [tasks/vision_pipeline.py:analyze_presentation_task](../backend/app/tasks/vision_pipeline.py), см. [DATA_FLOW §6.2](DATA_FLOW.md)) ловит исключение конкретного слайда и подставляет `""`, продолжая обход остальных слайдов; весь прогон падает только если пустыми оказались ВСЕ слайды (п.6 в §6.2).
- `routers/slides.py:regenerate_slide_text` ловит исключение и вызывает `billing_service.release_credits`, сохраняя инвариант `RESERVE → charge/release`.

**Альтернативы:**
- **Молча возвращать `""` из `_call_ollama`.** Отклонено — ровно то, от чего предостерегает комментарий в коде: слайд тихо остаётся без озвучки, и это не видно ни в логах, ни пользователю (тот же класс проблемы, что в [KNOWN_PROBLEMS §2.5](KNOWN_PROBLEMS.md)).
- **Ронять весь `analyze_presentation` при первом же пустом слайде.** Отклонено — один сбойный запрос к модели не должен обнулять уже полученный текст остальных слайдов; текущая деградация «плохой слайд → пустая озвучка» дешевле для пользователя, чем полный перезапуск.

**Trade-offs:**
- + Сбой виден сразу в логах (`vision_empty_content`) и не маскируется под «модель ничего не сказала об этом слайде».
- + Частичный сбой не убивает весь прогон — деградирует только затронутый слайд.
- − Слайд с пустой озвучкой всё равно долетает до `ready_for_edit`, если хотя бы один другой слайд получил текст — пользователю нужно заметить пробел и отредактировать вручную.

---

## Связанные документы

- [ARCHITECTURE.md](ARCHITECTURE.md) — где эти решения видны в общей картине.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — последствия некоторых решений (особенно 4, 5, 8, 9).
- [DATA_FLOW.md](DATA_FLOW.md) — как эти решения работают вместе в конкретных сценариях.

## 45. Переход LLM/Vision/TTS на Yandex AI Studio + SpeechKit v3 (2026-08-12)

Контекст: грант Yandex Cloud 10 000 ₽ на запуск. Текст и vision переключены на
`https://ai.api.cloud.yandex.net/v1` (OpenAI-совместимый режим, VISION_PROVIDER
остаётся `ollama` — это имя означает «любой OpenAI-совместимый эндпоинт» в
данном проекте, не буквально Ollama). TTS — на Yandex SpeechKit API v3
(`tts_service._synthesize_yandex`), а не v1: v3 вдвое дешевле (тарификация по
250-символьным юнитам вместо посимвольной).

> **Поправка (2026-08-16).** Здесь раньше утверждалось, что v3 «по умолчанию
> отдаёт полное качество». Это неверно: `containerAudio`/WAV отдаёт 22050 Гц —
> ровно столько же, сколько v1. Замер показал, что 22050 Гц — нативная частота
> самих голосов, поэтому решение оставить `containerAudio` в силе, но по другой
> причине. См. §43.

Важные ограничения v3, подтверждённые вживую 2026-08-12:
- Жёсткий лимит длины текста в одном запросе — между 400 и 500 символами
  (не 250, как можно понять из тарификации). YANDEX_TTS_MAX_CHARS = 200 —
  с запасом.
- Не у каждого голоса есть все амплуа. Проверено: alena/anton/zahar —
  neutral+good; marina — neutral+friendly; omazh — только neutral; filipp —
  без амплуа вовсе. "friendly" существует только у marina. Полный набор
  neutral+friendly+good не поддерживается ни одним голосом. Список пар
  голос:амплуа зафиксирован в YANDEX_TTS_ROLES_BY_VOICE (constants.py) и
  дублируется во frontend/src/composables/useVideoGeneration.ts — расширять
  только после проверки на живом API.
- Премиум-голоса (uliana и т.п.) и голоса :rc (zahar:rc и т.п.) недоступны
  на текущем ключе (403 Feature permission denied) — не включать в списки
  без отдельного разрешения от Яндекса.
- SpeechKit v1 оставлен в коде как исторический путь (TTS_PROVIDER=yandex
  раньше указывал на v1); текущий провайдер вызывает только v3.

Не переносить на Yandex: TTS до v3 требовал бы `raise NotImplementedError`
(закрыто), полноценный SpeechKit v1 не удалён из кода, но не используется.

## 43. SpeechKit v3: остаёмся на `containerAudio` — 22050 Гц это нативная частота голосов (2026-08-16)

Контекст: подозрение, что TTS звучит приглушённо, потому что
`outputAudioSpec.containerAudio` не принимает параметр частоты, а документация
AI Studio указывает для `outputAudioSpec` дефолт **22050 Гц**. Проверка на диске
подтвердила: все файлы в `tts_chunk_cache`, синтезированные Яндексом, — 22050 Гц
(для сравнения Silero и Polza там же лежат в 48000). Гипотеза: перейти на
`rawAudio` + `sampleRateHertz: 48000` (v3 допускает 8–48 кГц) и получить вдвое
большую полосу.

**Гипотеза не подтвердилась.** Замеры на живом API 2026-08-16:

| Запрос | Заголовок | Реальный спектр | Байты |
|---|---|---|---|
| `containerAudio: WAV` | 22050 Гц | контент до ~11020 Гц | 1.0x |
| `rawAudio @48000` | 48000 Гц | контент до ~11000 Гц | **2.18x** |

В варианте `rawAudio@48000` спектр обрывается на 11025 Гц (граница Найквиста для
22050) со ступенькой **−52.9 дБ**, а выше 12 кГц стоит ровная полка −111 дБ, то
есть шум квантования, а не звук. Прогон по всем 15 голосам из
`YANDEX_TTS_VOICES` (alena, filipp, marina, zahar, …) дал одинаковый спад на
10.5–11 кГц у каждого.

Вывод: 22050 Гц — нативная частота акустической модели SpeechKit, а не
ограничение формата передачи. Запрос 48 кГц заставляет Яндекс ресемплить на
своей стороне и удваивает трафик и объём кэша при нулевом выигрыше в качестве.
Апсемплинг до 48 кГц всё равно происходит ниже по пайплайну — в FFmpeg, при
сведении с видео, где он нужен только для единообразия с выходом Silero.

Решение: **оставить `containerAudio: WAV`**. Не «чинить» это на `rawAudio` —
проверено, выигрыша нет, есть только рост расхода. Если качество TTS реально
надо поднять, рычаг не в `outputAudioSpec`, а в смене голоса/провайдера
(премиум-голоса Яндекса на текущем ключе недоступны — 403, см. запись от
2026-08-12).

## 44. `access_code` курса: генерируется сразу при создании, но остаётся nullable

`courses.access_code` уже был `UNIQUE` (см. закрытый пункт KNOWN_PROBLEMS 2.1) —
тех-долг, который эта задача должна была закрывать, оказался уже закрыт раньше.
Реальный баг был в другом: `POST /courses/` не проставлял `access_code` вовсе,
поэтому вкладка «Доступ» показывала пустой код и ссылку `/join?code=null`, пока
преподаватель вручную не жал «Обновить код».

Рассматривался вариант дополнительно сделать колонку `NOT NULL`. Отклонён:
`DELETE /courses/{id}/access-code` намеренно обнуляет `access_code` при
переключении обратно в режим «по ссылке» — это legit-состояние, а не
недосмотр, и на нём стоит существующий тест
(`test_delete_access_code_resets_to_link_mode`). `NOT NULL` сломал бы этот
поток при первом же вызове. Оставили `nullable=True`.

Решение: `assign_unique_access_code` (services/course_service.py) переиспользует
существующий генератор кода и вызывается из `create_course`, а «Обновить код»
переведён на тот же путь — с ретраем всего цикла генерация+commit на
`IntegrityError` (гонка между pre-check SELECT и записью), а не с однократным
падением в 500. Бэкофилл для уже существующих курсов без кода — миграция
`865f7e4ba3a5` (чистая data-migration, без DDL), с тем же построчным
retry-on-`IntegrityError` через SAVEPOINT.

---

## 46. Автодеплой: сборка образов на сервере по SSH, а не registry + pull (2026-08-14)

**Контекст:** нужен был реальный CI/CD-деплой на push в `master` (до этого — вручную,
см. историю §37/раздел 7 DEPLOYMENT.md). Первая версия воркфлоу собирала образы в
GitHub Actions и пушила их в Yandex Container Registry (`build-and-push`), сервер их
только вытягивал.

**Решение:** `build-and-push`-джоб убран. `deploy/deploy.sh` собирает `edllm-backend:<sha>`/
`edllm-frontend:<sha>` **прямо на сервере** (`docker compose ... build`), CI лишь SSH'ится
и запускает скрипт. Перед миграцией — проверка `alembic current` vs `alembic heads`:
расходятся → `pg_dump -Fc` через сервис `db_backup`, затем `migrate`; совпадают → апгрейд
пропускается целиком. После пересоздания контейнеров — локальный smoke-test
(`/health` + `/docs`, до 12 попыток по 10с); провал → автоматический откат на
`last_good_sha` (последний успешно задеплоенный sha, без пересборки) и **всегда** красный
job — даже если откат прошёл успешно, это сигнал, что что-то было не так.

**Альтернативы:**
- **Registry (YCR) + pull на сервере.** Реализовано, затем отклонено: для масштаба проекта
  (1 сервер, 1 разработчик) отдельный registry — лишний слой инфраструктуры и лишняя точка
  отказа (нужны отдельные креды, сеть до YCR с сервера, синхронизация тегов). Сборка на
  сервере проще и достаточна, пока не появится второй сервер/множественные окружения.
- **Blue-green / отдельный staging-хост.** Не рассматривалось всерьёз — при одном
  production-сервере это over-engineering; smoke-test + auto-rollback даёт сопоставимую
  защиту от битого деплоя при на порядок меньшей сложности.

**Trade-offs:**
- + Минимум инфраструктуры: ни registry, ни второго хоста, ни лишних кредов, кроме SSH-ключа.
- + Auto-rollback без пересборки (образ `last_good_sha` уже локальный) — откат быстрый.
- + Условный дамп бережёт диск и время: дамп снимается только когда реально меняется схема.
- − Единая точка отказа — сам сервер: пока идёт `docker compose build`, приложение продолжает
  работать на старых контейнерах, но если сервер недоступен по SSH, деплой невозможен вообще.
- − `deploy.sh` — bash-скрипт с ручным state-файлом (`~/.edllm-deploy/last_good_sha`), а не
  декларативный оркестратор — при росте числа серверов не масштабируется без переписывания.

## 47. База знаний урока: `LessonMaterial` + `LessonNote` в одном роутере (2026-08-19)

Преподавателю нужно прикладывать к уроку вспомогательные файлы (методички, PDF,
архивы) и писать текстовые конспекты, а записанный студент должен видеть их на
вкладке урока. Никакого AI: только ручной ввод.

**Решение — две плоские сущности + один роутер, гейты берутся готовые:**

- `LessonMaterial` (файл + `title`/`description`/`size_bytes`/`uploaded_by`) и
  `LessonNote` (`title` + markdown `content` + `order`) — обе с
  `ondelete="CASCADE"` на `lessons.id` и `eager_defaults=True` (обе правятся
  PATCH'ем, см. решение про `onupdate=func.now()`).
- **Один роутер** `routers/lesson_materials.py` (как `comments.py`, не сплит
  teacher/student как у assignments): чтение — `GET /lessons/{id}/knowledge`
  под `require_lesson_access` (владелец **или** записанный студент, черновик →
  404), запись — те же `/lessons/{id}/…` пути под `get_owned_lesson`.
  Вложенность записи под `lesson_id` — не косметика: она и есть проверка
  владения, никакой ownership-логики в сервисе нет.
- `can_edit` в ответе — решение сервера (`is_owner` из `require_lesson_access`),
  фронт не угадывает роль. Один компонент `KnowledgePanel` на оба кабинета.
- Файлы **только сохраняются, никогда не парсятся** — whitelist
  `LESSON_MATERIAL_EXTENSION_MIME` → категория → `validate_upload`
  (magic-байты, zip-slip/zip-bomb) → `save_upload_bounded` с жёстким
  стриминговым лимитом. Свои константы, а не переиспользование `ATTACHMENT_*`:
  у материалов другой профиль (30 файлов, 2 ГБ на урок, **без ретеншна**).
- Синхронное сохранение, без новой очереди Celery — как у вложений заданий и
  загрузки PPTX.
- Ссылки на скачивание — `storage_service.get_url(..., SIGNED_URL_TTL_MATERIAL)`:
  HMAC-подпись на local, presigned на S3. Код одинаковый на обоих бэкендах.
- **Удаление файлов из хранилища — часть контракта, а не бонус:** `delete_material`
  сначала стирает объект, потом строку (падение между шагами оставляет сироту-файл,
  который добьёт purge, а не строку без байтов); `purge_pipeline._purge_material_files`
  + префикс `materials/{lesson_id}` в `_remove_lesson_dirs` вычищают материалы при
  хард-удалении урока/курса/пользователя. Софт-удаление урока материалы не трогает.

**Альтернативы:**
- **Одна сущность с `kind` (файл|заметка).** Отклонено: половина колонок всегда
  NULL, а лимиты/валидация у них общего не имеют ничего.
- **Teacher/student-сплит роутеров как в assignments.** Оправдан там, где у ролей
  разные ресурсы (сдачи, оценки). Здесь ресурс один и читается одинаково —
  сплит дал бы два пути к одному списку и второй шанс разойтись в правиле доступа.
- **Markdown-библиотека на фронте.** Отклонено: новая зависимость ради подмножества
  синтаксиса. `utils/markdown.ts` рендерит **VNodes** (не `v-html`), схемы ссылок
  ограничены http(s)/mailto — сырой HTML из конспекта физически не может стать
  разметкой.

**Trade-offs:**
- + Правило видимости не продублировано: draft → 404 приходит из
  `require_lesson_access`, менять его нужно в одном месте.
- + Одинаково работает на local и S3, включая очистку — S3-объекты удаляются тем же
  `storage_service.delete_file`/`delete_prefix`.
- − Файл нельзя заменить, не пересоздав материал: PATCH правит только метаданные
  (зато удаление из хранилища остаётся чистым однонаправленным путём).
- − Свой markdown-рендерер поддерживает лишь подмножество (заголовки, списки,
  цитаты, fenced code, inline-разметка, ссылки); таблицы и картинки не рендерятся.
- − `PUT /notes/order` требует полный список id урока — переупорядочивание из двух
  вкладок одновременно даст 400 вместо тихого мержа (осознанно: плотный `order`).

## 48. Метеринг AI-проверки и платное продление хранения — один кредитный леджер (2026-08-19)

Два расхода, которые раньше были бесплатны и неограниченны: LLM-проверка открытых
ответов студентов и хранение файлов сдач. Оба надо было ограничить, не заводя
отдельную валюту, не ломая маркетинговое «AI-проверка бесплатна» и не превращая
сдачу студента в операцию, которая может упасть из-за пустого баланса учителя.

**Решение — общий кредитный баланс + бесплатный технический пол, одинаковый на всех тарифах:**

- **Одна валюта на оба механизма.** Превышение квоты AI-проверки и продление
  хранения списываются теми же кредитами, что и генерация видео, через
  существующий `RESERVE → charge/release` (`billing_service`). Новых способов
  списания не заведено; добавлены только операции `QUIZ_GRADE` и
  `RETENTION_EXTEND` в enum `credit_operation`.
- **Бесплатная месячная квота — `AI_GRADING_FREE_ANSWERS_PER_MONTH`, вне
  `PLAN_CONFIGS`.** Это технический пол против злоупотреблений, а не тарифная
  ступень: free и school получают одинаково. Счётчик — тот же
  `usage_counters` и тот же атомарный `INSERT … ON CONFLICT DO UPDATE … WHERE
  count < :limit RETURNING`, что у lifetime-триала, только `period_key='YYYY-MM'`.
  Гонка невозможна по построению: проигравший не находит строку под UPDATE и
  честно проваливается в платный путь.
- **Гранулярность метеринга — отдельный открытый вопрос, не попытка целиком.**
  Вопрос — это и есть единица LLM-вызова и единица деградации. Попытка из 10
  вопросов не может стоить столько же, сколько из одного, а при частичном
  бюджете часть ответов проверяется, остальные помечаются `needs_review`.
- **Деградация тихая.** Нет квоты и нет кредитов → LLM не вызывается, ответ
  остаётся `needs_review=true` с пояснением для преподавателя. Сдача студента не
  блокируется, не задерживается и не показывает ошибку — платит и решает
  преподаватель, а последствия не должны доставаться студенту.
- **Биллинг вынесен из транзакции с оценками.** Метеринг выполняется на главном
  потоке таски **до** пула (psycopg2 `Session` не потокобезопасна — нельзя
  списывать из воркер-тредов), а расчёт холдов — **после** финального commit
  оценок: `sync_finalize_generation` умеет делать `rollback()`, и общая
  транзакция с мутациями ответов стоила бы уже выставленных оценок.
- **Эффективный срок хранения — `COALESCE(attachments_retain_until, graded_at +
  ATTACHMENT_RETENTION_DAYS_AFTER_GRADED)`**, две nullable-колонки на
  `AssignmentSubmission`. Purge и API читают одно выражение
  (`retention_service`), в SQL оно раскрыто как ветка по колонке, а не как
  interval-арифметика — оба порога считаются в Python, запрос остаётся
  индексируемым сравнением timestamp'ов.
- **Продления складываются от текущего дедлайна, не от `now()`** — продлить
  заранее не должно стоить остатка оплаченного срока. Повторный вызов — это
  вторая покупка, а не идемпотентный no-op; ответ всегда несёт актуальный
  `attachments_expire_at`.
- **Цена продления формульная, не плоская:**
  `estimate_retention_extension = RETENTION_EXTEND_BASE_CREDITS +
  ceil(bytes / RETENTION_MB_PER_CREDIT)` — чистая функция рядом с
  `estimate_video_text/auto`. Хранение оплачивается байтами, поэтому 1 ГБ видео
  стоит ~6× дороже 200 КБ текста. `CREDIT_WEIGHTS["retention_extend"]` оставлен
  как витринная цифра прайс-листа (совпадает с ценой типовой мелкой сдачи) — тот
  же приём, что `quiz_grade: 0`.
- **Напоминание — одноразовое на окно хранения**, guard-колонка
  `retention_reminder_sent_at`, суточная задача в **существующем единственном**
  beat (`celery_quiz`). Оплаченное продление сбрасывает guard: новое окно
  заслуживает своего письма.

**Альтернативы:**
- **Отдельная таблица `retention_extensions` вместо двух колонок.** Отклонено:
  история продлений уже есть в `credit_transactions` (`ref_id` = id сдачи), а
  purge получил бы JOIN с агрегатом вместо сравнения одной колонки.
- **Метеринг за попытку целиком.** Отклонено: одна резервация проще, но цена
  перестаёт зависеть от числа открытых вопросов, и исчезает частичная
  деградация — вся попытка либо проверяется, либо уходит в ручную очередь.
- **Плоская цена продления (как было в первой версии).** Отклонено: хранение —
  расход, пропорциональный байтам; плоская цена одинаково наказывает текстовую
  сдачу и премирует гигабайтную.
- **Своя таблица счётчиков под AI-квоту.** Отклонено: `usage_counters` уже даёт
  ровно нужную семантику `(user, period, resource)` с доказанной атомарностью —
  вторая реализация того же означала бы второй способ ошибиться в гонке.
- **Post-paid списание за продление (сначала продлить, потом списать).**
  Отклонено: расходится с остальными платными операциями и допускает
  отрицательный баланс. Обычный `RESERVE → charge` + отказ 409 **до** резерва,
  если файлы уже удалены.

**Trade-offs:**
- + Один леджер и один паттерн списания на все платные операции: аудит,
  идемпотентность и отмена работают везде одинаково.
- + Бесплатная квота не привязана к тарифу, поэтому смена цен на планы не требует
  трогать метеринг, а «AI-проверка бесплатна» остаётся правдой для большинства.
- + Никакой миграции поведения для текущих пользователей: в пределах квоты всё
  работает ровно как раньше.
- − **Цена продления считается от объёма на момент клика, а не на момент сдачи.**
  Если преподаватель после первого продления догрузил feedback-файлы, следующее
  продление подорожает — и наоборот, удаление файлов его удешевит.
- − Превью цены в списке сдач может разойтись с фактическим списанием, если объём
  изменился между рендером и кликом. Сервер пересчитывает цену авторитетно, так
  что списание всегда корректно, но показанное число может оказаться устаревшим.
- − Квота не переносится между месяцами и не пропорциональна остатку месяца: аккаунт,
  созданный 30-го числа, получает полную квоту на один день, потом новую.
- − Гранулярность «за вопрос» даёт N резерваций на попытку вместо одной — больше
  строк в `credit_transactions` и более шумная история у активных преподавателей.
- − Метеринг последовательный (главный поток), поэтому попытка с большим числом
  открытых вопросов делает N быстрых UPSERT'ов до начала параллельного grading'а.

---

## 49. `POST /quiz/ai-review` — убран из-под кредитов, всегда бесплатен (2026-08-20)

**Контекст:** `ai_review` (`routers/quiz_teacher.py`) — синхронная, дешёвая для
повтора QA-проверка LLM'ом вопросов теста самим преподавателем перед публикацией
(не путать с §48 — там про free-плановую квоту LLM-оценки *студенческих* ответов).
Эндпоинт был заведён через обычный `RESERVE → charge/release` с
`CREDIT_WEIGHTS["ai_review"] = 2` и без триала («No trial — credits only»). Но
free-план не даёт `onetime_credits` (§48/`PLAN_CONFIGS`) — баланс на этой операции
у любого free-аккаунта равен 0 с первого дня, так что `reserve_credits` детерминированно
возвращал `False`, и любой преподаватель на free-плане получал `402
insufficient_credits` на первой же попытке. Сам `reserve_credits` при этом не падает
(проверено вызовом напрямую на реальном 0-балансовом аккаунте) — 402 отдавался
корректно, но продуктово это делало QA-проверку своего же теста платной функцией,
хотя задумывалась она бесплатной.

**Решение:** убрать `reserve_credits`/`charge_credits`/`release_credits` из
`ai_review` целиком — эндпоинт больше не трогает `billing_service`.
`CREDIT_WEIGHTS["ai_review"]` оставлен (используется только для витринного поля
`ai_review_credits` в `/generation-estimate`), значение выставлено в `0`, чтобы
оценка не врала о несуществующей цене. Анти-абьюз — уже существующий
`@limiter.limit("5/minute")` на роуте, отдельную квоту заводить не стали: в коде
не нашлось никакой существующей инфраструктуры лимита именно под `ai_review`
(константа `AI_GRADING_FREE_ANSWERS_PER_MONTH=100` — про другую фичу, §48), а
заводить новую под неподтверждённое требование — не по Simplicity First.
`usage_service.set_usage_context("ai_review", …)` оставлен: это учёт ₽-стоимости
у провайдера для маржи (Prometheus cost collector), не биллинг пользователя.

**Альтернативы:**
- **Почистить `reserve_credits`, чтобы не 402'ить, а тихо деградировать.**
  Отклонено: сам `reserve_credits` уже корректен (не бросает исключение) — чинить
  там нечего, проблема была не в обработке ошибки, а в том, что операция вообще
  должна быть платной.
- **Завести лимит вроде `AI_REVIEW_FREE_CALLS` по образцу `usage_counters`.**
  Отклонено как преждевременное: продуктового решения «сколько именно» не было,
  только предположение «может быть 100»; рейт-лимит на роуте уже ограничивает
  злоупотребление. Если абьюз станет реальной проблемой — есть готовый паттерн
  (§48) для повторного использования.

**Trade-offs:**
- + Free-план больше не блокируется на первой же QA-проверке своего теста.
- + Ноль новой инфраструктуры: убрано три вызова `billing_service`, никакой новой
  таблицы/квоты.
- − Нет верхнего предела на число LLM-вызовов кроме рейт-лимита 5/мин — если это
  окажется недостаточным анти-абьюзом, квоту придётся добавить отдельно.

## 50. Загрузки (`uploads.py`) переведены с `require_verified_teacher` на `require_teacher` (2026-08-20)

**Контекст:** `require_verified_teacher` задуман как гейт именно для *AI-операций*
(см. докстринг в `dependencies.py` и `AI_GATED_ENDPOINTS`), но исторически на него
также навесили четыре чисто контентных эндпоинта в `routers/uploads.py` —
`POST /pptx`, `POST /script`, `POST /video`, `POST /cover`. Ни один из них не
вызывает LLM/vision/TTS: это просто сохранение файла на диск (и, для `/script`,
локальная экстракция текста без сети). При этом ни один из них не входит в
`AI_GATED_ENDPOINTS` — то есть даже guard-тест `test_ai_gating_guard.py` не считал
их AI-операциями, и сам факт email-гейта на них был расхождением между кодом и
задуманной семантикой. `routers/courses.py` (создание/изменение курса, модулей) и
`routers/lessons.py` (создание урока) на момент проверки уже сидели на
`require_teacher` — там расхождения не было, менять было нечего.

**Решение:** заменить `Depends(require_verified_teacher)` на
`Depends(require_teacher)` во всех четырёх upload-роутах. `require_verified_teacher`
остаётся как есть и продолжает гейтить `POST /lessons/{id}/analyze`
(`routers/slides.py`) и `POST /lessons/{id}/generate-video` (`routers/lessons.py`) —
единственные два места, где он реально закрывает LLM/vision/TTS вызов.

**Альтернативы:**
- **Добавить uploads-эндпоинты в `AI_GATED_ENDPOINTS` вместо смены зависимости.**
  Отклонено: это узаконило бы неверную предпосылку, что загрузка файла — AI-операция,
  и лишь усложнило бы guard-тест без изменения продуктового смысла.
- **Завести отдельный `require_teacher_no_email_check` алиас.** Отклонено:
  `require_teacher` уже делает ровно то, что нужно (роль teacher, без проверки
  email) — плодить синоним не по Simplicity First.

**Trade-offs:**
- + Неверифицированный email преподавателя больше не блокирует загрузку PPTX/скрипта/
  видео/обложки — блокируются только реальные AI-запросы (analyze, generate-video
  и уже существующие `require_verified_email`-эндпоинты).
- + Код и `AI_GATED_ENDPOINTS` теперь согласованы: всё, что сидит на
  `require_verified_teacher`/`require_verified_email`, действительно AI-операция.
- − Не найдено.

---

## 51. Архив курса не отзывает доступ у записанного студента; purge пропускает курсы с записями (2026-08-21)

Уточняет и расширяет ADR «Soft delete: глобальный фильтр для User/Lesson, явный — для Course»
(там исходно было записано «teacher видит архив, студент — нет»).

**Контекст:** архивация (`DELETE /courses/{id}` → `deleted_at`) задумывалась как «убрать курс
с глаз преподавателя», но по факту читалась студентами как отзыв доступа, а через
`SOFT_DELETE_PURGE_DAYS` (30) purge физически стирал курс. Все FK в цепочке
`courses → modules → lessons → enrollments → lesson_progress` (а также попытки квизов и
сдачи заданий) объявлены `ondelete=CASCADE`, поэтому хард-удаление архивного курса уносило
и **собственную** запись студента: прогресс, оценки, историю попыток, сданные файлы.
Преподаватель, наводивший порядок в списке курсов, необратимо удалял чужие данные.

**Решение:**

- **Архив — чисто teacher-facing действие.** Единственное правило видимости контента
  остаётся `module.is_published AND lesson.is_published` в `services/visibility_service.py`;
  `course.deleted_at`, как и `course.is_published`, в него не входит. Уже записанный студент
  видит и открывает архивный курс ровно так же, как активный.
- **Новая запись на архивный курс запрещена — 404.** `routers/students.py:enroll` проверяет
  `deleted_at` **независимо** от `is_published` (курс можно заархивировать, не снимая с
  публикации). Раньше архив отдавал 400 — теперь 404, как и для черновика: API не сообщает,
  что архивный курс существует. `/courses/preview` фильтр по `deleted_at` сохраняет — это
  тоже discovery.
- **`purge_soft_deleted` никогда не удаляет курс, у которого есть хотя бы одна `Enrollment`** —
  бессрочно, независимо от возраста `deleted_at` (`_course_purge_guard` в
  `tasks/purge_pipeline.py`). Курсы с `enrollment_count == 0` пуржатся по прежнему таймингу;
  `SOFT_DELETE_PURGE_DAYS` не меняется, нового тумблера не заводим — правило булево.
- **Проверка — под блокировкой строки, в одной транзакции с DELETE.**
  `SELECT courses.id … FOR UPDATE SKIP LOCKED` с повторённым предикатом
  `deleted_at IS NOT NULL AND deleted_at < cutoff`, затем `COUNT(enrollments)`. INSERT в
  `enrollments` берёт на родительской строке `FOR KEY SHARE`, который конфликтует с
  `FOR UPDATE`: либо блокировку первыми берём мы (конкурентный enroll ждёт нашего коммита),
  либо строку занял enroller и мы её пропускаем до следующего прогона — а там запись уже
  видна и курс сохраняется навсегда. Тот же перечитанный предикат закрывает гонку
  restore/purge (курс восстановили после сканирования). Пропуск всегда безопасен: purge
  идемпотентен и сканирует ежедневно.
- **UI не обещает удаление, которого не будет.** `CourseOut.days_until_purge` отдаёт `null`
  при `enrollment_count > 0`; `GET /courses/grouped` для этого считает `enrollment_count`
  одним агрегатом. Confirm-копи на карточке курса и на странице курса переписаны.

**Альтернативы:**

- *Анонимизировать/переносить прогресс перед каскадом* — сложный ETL ради сценария, где
  правильный ответ «просто не удалять».
- *Разорвать CASCADE на `enrollments`/`lesson_progress`* — миграция схемы, осиротевшие строки
  без курса и мёртвый FK-мусор; предикат в purge проще и обратим.
- *Считать enrollment один раз при сканировании* — окно гонки между подсчётом и DELETE.
- *`SELECT … FOR UPDATE` без `SKIP LOCKED`* — таск встаёт на конкурентном enroll; пропуск
  до следующих суток дешевле.
- *Новый флаг «критерий пурга» в `constants.py`* — нечего конфигурировать, правило булево.

**Trade-offs:**

- + Преподаватель не может, наводя порядок, необратимо стереть чужие оценки и историю.
- + Архив/restore идемпотентны, teacher-архив (`/courses/grouped`, restore) не изменился.
- − **Хранилище растёт монотонно:** видео, PPTX, слайды и вложения курса с записями не
  удаляются никогда. `gc_lesson_videos` по-прежнему подчищает неопубликованные версии, а
  вложения сдач — retention-свип, но опубликованный MP4 остаётся навсегда. Это осознанная
  плата; если станет больно — отдельным решением вводить «удалить курс насовсем» с явным
  подтверждением преподавателя, а не тихий таймер.
- − Карве-аут только на пути Course. Purge **пользователя** по-прежнему каскадом уносит его
  курсы вместе с записями: удаление аккаунта — другой рычаг (право на удаление данных), и
  вечное удержание аккаунта ради чужих enrollment создало бы противоположную проблему.

---

## 52. Мобильная навигация: один бургер в `AppHeader` + композабл состояния (2026-08-24)

**Контекст:** бургер в `AppHeader.vue` не работал: компонент держал `const open = ref(false)`
и `@click="open = !open"`, но ни одного `v-if="open"` в шаблоне не было — панель просто не
существовала. Оба блока десктопного меню скрыты за `hidden md:flex`, поэтому под 768px в
приложении не было **никакой** навигации. Параллельно `student-cabinet`/`student` имеют
собственный сайдбар-дровер, так что нужно было решить, сколько точек входа в меню на мобиле.

**Решение:** состояние вынесено в `composables/useMobileMenu.ts` (открытие/закрытие, закрытие
по смене маршрута, Escape, блокировка `body`-скролла с восстановлением прежнего значения,
очистка в `onScopeDispose`, возврат фокуса на кнопку через `triggerRef`). `AppHeader`
рендерит панель через `<Teleport to="body">` — так stacking-контекст sticky-шапки не может её
обрезать или перекрыть. Пункты меню зеркалят десктопную навигацию: `AppSidebar` для
преподавателя, `StudentSidebar` для студента. Сайдбар-дроверы кабинетов оставлены как есть,
но их кнопки получили подписи («Разделы», «Уроки»), чтобы два одинаковых бургера подряд не
читались как дубль. У обоих `<Transition>` задан явный `:duration` — закрытие резолвится по
таймеру, а не по `transitionend`.

**Альтернативы:**

- *Держать состояние прямо в `AppHeader`* — невозможно покрыть тестами: `@vue/test-utils` в
  проекте нет, а новые зависимости запрещены. Композабл гоняется в `effectScope`, за счёт чего
  проверяется и `onScopeDispose`.
- *`onUnmounted` вместо `onScopeDispose`* — требует инстанса компонента, тест пришлось бы
  монтировать.
- *Рендерить панель на месте, без `Teleport`* — `header` имеет `sticky` + `z-30`, то есть свой
  stacking-контекст; панель пришлось бы гонять по z-index против шапки.
- *Слить кабинетный дровер с меню шапки* — сломало бы разделение `student-cabinet`/`student`
  (см. §34 и структуру layout'ов) ради косметики.
- *Полагаться только на `transitionend`* — событие не приходит в фоновой вкладке (Chrome
  останавливает rAF и не проигрывает CSS-переходы), и узел остаётся висеть в DOM.

**Trade-offs:**

- + Единая точка входа в навигацию на мобиле на всех layout'ах, включая `bare` и `workspace`,
  где сайдбара нет вообще.
- + Блокировка скролла снимается даже при размонтировании посреди навигации.
- − **Список пунктов продублирован:** `TEACHER_NAV`/`STUDENT_NAV` в `AppHeader` повторяют
  `AppSidebar.items` и `StudentSidebar.items`. Общий источник потребовал бы отдельного модуля
  ради трёх и пяти строк; при изменении разделов надо править оба места (в коде стоит
  комментарий-напоминание).
- − На страницах кабинета студента на мобиле две кнопки меню: бургер шапки (аккаунт, выход,
  поддержка) и «Разделы» (навигация кабинета). Разведены подписями, но это компромисс.

---

## 53. Zero-downtime деплой: blue-green web-слоты + nginx include & reload на одном хосте (2026-08-26)

**Контекст:** до этого `deploy/deploy.sh` роллаутил релиз шагом `up -d --force-recreate` для
`backend` и `frontend` (§46). На одном хосте это означало, что оба контейнера пересоздаются
одновременно и на десятки секунд отдают 502: пользователи в этот момент ловили обрыв, а
открытая страница урока с активной генерацией теряла SSE-стрим прогресса. Целевое состояние —
обычный релиз без единой 5xx, при этом без новой инфраструктуры (один сервер, без registry,
без оркестратора).

**Решение:** web-слой переведён на **blue-green на том же хосте**.

- `docker-compose.prod.yml` описывает по два слота через YAML-anchor'ы `x-backend-web` /
  `x-frontend-web`: `backend_blue`/`backend_green` и `frontend_blue`/`frontend_green`. Слоты
  отличаются только `container_name` и профилем. Портов наружу не публикуют — только
  `edu-network`. `blue` без профиля (голый `up -d` из DEPLOYMENT §7 поднимает рабочий стек),
  `green` под `profiles: ["green"]` (вне окна деплоя не стоит и памяти не ест).
- nginx проксирует на upstream'ы из отдельного включаемого файла `nginx/upstreams/active.conf`
  (`include /etc/nginx/upstreams/*.conf;`), который перезаписывает деплой-скрипт. Переключение =
  перезапись файла + `nginx -t` + **`nginx -s reload`** (не restart): reload оставляет уже
  установленные соединения на старых worker-процессах до их завершения. Переключение слотов
  сознательно **не** заведено в envsubst — `NGINX_ENVSUBST_FILTER` остаётся пришпиленным к
  `${DOMAIN}`.
- `nginx` **не имеет** `depends_on` на слоты: после переключения на green слот blue погашен, и
  любой `up -d nginx` поднял бы мёртвый слот (+2.5 GiB). Include всегда называет ровно один —
  по построению работающий — слот, поэтому `nginx -t` не падает на нерезолвящемся хосте.
- Порядок роллаута: build → migration guard → [дамп] → migrate → поднять целевой слот →
  дождаться `healthy` (`docker inspect` + кросс-сервисная проба изнутри целевого backend) →
  переключить upstream → reload → smoke через nginx → retag `:local` → пересоздать
  Celery-воркеры → погасить старый слот → записать состояние. Провал ДО переключения — целевые
  контейнеры удаляются, прод не тронут; провал ПОСЛЕ — upstream возвращается на старый слот
  (он ещё жив). Автооткат на `last_good_sha` остался — теперь как путь для поздних падений,
  когда старый слот уже погашен.
- Образ выбирается одной переменной `IMAGE_TAG` (`edllm-backend:${IMAGE_TAG:-local}`), которую
  скрипт экспортирует; `BACKEND_IMAGE`/`FRONTEND_IMAGE` убраны. На успехе `:local`
  перетегируется на задеплоенный sha, поэтому ручной путь §7 работает без переменных.

**Дренаж.** gunicorn получил явные `--timeout ${GUNICORN_TIMEOUT:-120}` и
`--graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-45}`, слоты — `stop_grace_period: 60s`
(инвариант: graceful-timeout строго меньше stop_grace_period, иначе Docker убьёт мастер
посреди дренажа). SSE-стрим прогресса не завершается сам по себе, поэтому при выводе слота он
обрывается по дедлайну — и это нормально: `progress_stream` теперь первым кадром отдаёт
`retry:` (`SSE_RETRY_MS`), а на реконнекте заново отдаёт снапшот прогресса из Celery/Redis.
`useProgressStream` дополнительно получил ретрай с backoff (1-2-4-8с) на случай, когда
реконнект попал в неудачный момент и браузер закрыл EventSource окончательно; поллинг
`/task-status` остался последним фолбэком.

**Celery — намеренно НЕ blue-green.** Воркеры пересоздаются после переключения web-слоя
(`up -d --force-recreate`, а не `restart`: restart не меняет образ). Warm shutdown по SIGTERM в
пределах `stop_grace_period` (video/vision — 120s), недоделанное переедет назад в очередь через
уже включённые `task_acks_late` + `task_reject_on_worker_lost`, а `video_pipeline` поднимет
работу с Redis-чекпоинта. Двойного списания не будет: RESERVE делает роутер (один раз на
запуск), а charge/release — `_settle_once` внутри таска. Beat остаётся ровно один
(`celery_quiz --beat`), очереди и инвертированные Redis-приоритеты не тронуты.

**Совместимость релизов N и N-1 (expand/contract).** Во время переключения и рестарта воркеров
две версии кода работают одновременно против одной БД и одних очередей. Отсюда два правила:

1. **Схема БД.** Миграция релиза N обязана быть совместима с кодом N-1: только добавление
   nullable-колонок, новых таблиц, индексов (`CONCURRENTLY`). `DROP`/`RENAME`/`SET NOT NULL` —
   отдельным следующим релизом. Проверяется автоматически: `app.scripts.migration_guard`
   разбирает ревизии между `alembic current` и `alembic heads`, смотрит **только тело
   `upgrade()`** и валит деплой ДО применения миграции. Обойти можно только явно —
   `DEPLOY_ALLOW_UNSAFE_MIGRATION=1`, и тогда релиз идёт через maintenance-страницу.
2. **Сигнатуры Celery-тасок.** Новый web может поставить задачу, которую подхватит ещё старый
   воркер (и наоборот). Поэтому: новые kwargs — **только опциональные, с дефолтом**; удаление
   или переименование аргумента, как и смена очереди, — следующим релизом. В `migration_guard`
   это намеренно не заведено (нечего парсить надёжно) — правило держится ревью.

**Maintenance-режим** — fallback, не основной путь. Флаг-файл `deploy/maintenance/ON` в
bind-mount'е nginx (монтируется **каталог**, потому что файла обычно нет); при его наличии
nginx отдаёт 503 + `Retry-After`: страницам — `_maintenance.html`, `/api/*` — JSON
фиксированной формы `{"code":"maintenance",...}`, чтобы SPA отличала плановые работы от
реальной ошибки. `/health`, `/healthz` и internal-локации идут в обход. Переключатель —
`deploy/maintenance.sh on|off`. Отдельно от этого есть **предупреждение заранее**: публичный
`GET /api/v1/system/status` отдаёт окно техработ из `MAINTENANCE_*` в `.env.prod`, а
`MaintenanceBanner` в `AppHeader` показывает его за `MAINTENANCE_NOTICE_HOURS` до начала и во
время. Без новой таблицы и без админки — окно правит тот, кто катит релиз.

**Альтернативы:**

- *Registry + оркестратор (k8s/Nomad/Swarm) с rolling update.* Даёт всё это из коробки, но
  это ровно та инфраструктура, которую §46 уже отверг для одного сервера: реестр, control
  plane, отдельный деплой-путь. Цена несопоставима с одним include-файлом.
- *`docker compose up -d` без `--force-recreate` / rolling через `--scale`.* Compose v2 не
  умеет rolling update с ожиданием готовности и дренажом: `up` останавливает старый контейнер
  до того, как новый начнёт отвечать. `--scale 2` на сервисе с фиксированным `container_name`
  невозможен, а без него nginx всё равно нужен способ узнать, кто уже готов.
- *Traefik / Caddy / consul-template с автообнаружением контейнеров.* Убрал бы шаг перезаписи
  include, но это новая зависимость в стеке ради одной строки конфига — прямо запрещено рамками
  задачи и не окупается на одном хосте.
- *Полное окно техработ на каждый релиз.* Просто и предсказуемо, но это ровно то, от чего
  уходим. Оставлено как fallback для разрушающих миграций.

**Trade-offs:**

- + Обычный релиз: ни одной 5xx, трафик переезжает по `reload`, старый слот дренируется.
- + Битый образ или не поднявшийся `/health` на новом слоте пользователи не замечают вообще —
  трафик остался на старом слоте, а CI красный.
- − **Пиковое потребление памяти в окне деплоя выше на ~2.5 GiB** (backend 2g + frontend 512m
  второго слота). Суммарные `deploy.resources.limits` при этом ≈ 13.25 GiB против ≈ 10.75 GiB
  в покое. Перекрытие сознательно минимизировано: старый слот гасится сразу после smoke-теста,
  а не держится «про запас». На хосте с малым запасом RAM это главный риск — перед первым
  таким деплоем стоит посмотреть `docker stats` (см. DEPLOYMENT §7).
- − Состояние деплоя размазано по двум местам: `nginx/upstreams/active.conf` (истина, её читает
  nginx) и `~/.edllm-deploy/active_slot` (зеркало). Скрипт всегда предпочитает первое и
  откатывается на второе, а при полном отсутствии обоих берёт `blue`.
- − Генерируемые файлы (`nginx/upstreams/active.conf`, `monitoring/targets/backend.json`)
  пришлось убрать из git: деплой их переписывает, и первый же коммит, тронувший их, заставил бы
  `git pull --ff-only` в CI отказаться мержить поверх локальной правки — деплои встали бы
  насовсем. Цена: свежий клон их не содержит, поэтому nginx до первого деплоя не стартует;
  лечится `deploy/deploy.sh --init-state`, а внутри скриптов — `ensure_generated_state`.
  Обнаружено на боевом сервере при первом переходе (`git status` показал `M active.conf`).
- − Слот `green` под профилем: `docker compose ps` без `--profile green` его не покажет, и это
  регулярно будет сбивать с толку при отладке. Поэтому `compose()` в `deploy/lib.sh` передаёт
  `--profile green` всегда.
- − Два определения сервиса вместо одного: забыть про anchor и поправить только один слот —
  реальный риск. Смягчено тем, что слоты не содержат ничего, кроме `<<: *anchor`,
  `container_name` и профиля.

---

## 54. Подсистема уведомлений: одна точка входа, urgent/digest, гейт присутствия по SSE (2026-08-26)

**Контекст:** продуктовое письмо было ровно одно — «видеолекция готова» из
`video_pipeline._enqueue_video_ready_email` прямым `send_email.delay(...)`. В план входили
уведомления о комментариях преподавателя, оценках, сообщениях в приватном треде задания и
сдачах работ. Наращивать это теми же прямыми вызовами означало N шаблонов и N мест, где можно
забыть проверить отписку. Плюс два конкретных дефекта уже существующей схемы: (1) при
`task_acks_late=True` + `task_reject_on_worker_lost=True` SIGKILL воркера после отправки, но до
ack, переигрывает задачу и письмо уходит повторно — а рестарт воркеров стал штатным шагом
каждого деплоя (§53), то есть окно дубликатов теперь регулярное; (2) генерация занимает
1.5–2 минуты, прогресс стримится по SSE, и пользователь, который смотрит на страницу урока,
получал письмо о том, что он видит на экране.

**Решение:** сквозная подсистема из двух половин.

- **`services/notification_service.py` — единственный API вызова:** `notify(user_id, event,
  payload)`. Не делает ничего, кроме `deliver_notification.delay(...)`, и никогда не бросает.
  Именно поэтому одна и та же функция годится и async-роутерам (комментарии, оценки, тред), и
  sync-Celery-таскам (видео, квизы) — async/sync-двойника не возникает. Здесь же живёт то, о
  чём обе половины обязаны договориться: реестр событий, раскладка Redis-ключей и подпись
  токена отписки.
- **Реестр вместо кода по местам:** `NotificationEvent` (6 значений) → `EventSpec` (класс
  доставки, категория-настройка, subject, строка заголовка, флаг гейта присутствия). Добавление
  события = одна запись в `REGISTRY`; guard-тест сверяет, что у каждого события есть спека, а
  значение каждой `NotificationCategory` — реальная колонка `User`.
- **Два класса доставки.** urgent (комментарий, оценка, сообщение в треде) уходит сразу.
  digest (урок готов, квиз сгенерирован, работа сдана) копится в Redis-накопителе на
  пользователя и раз в `NOTIFY_DIGEST_INTERVAL_MINUTES` сливается одним письмом. Флаш —
  в существующем единственном beat (`celery_quiz`, очередь `quiz`), второй beat не заводился.
- **Дедуп** — Redis-ключ `(user_id, event, entity_id)` с TTL из `constants.py`: проверка ДО
  отправки, установка ПОСЛЕ успешной. Тот же приём идемпотентности, что у `payment_pipeline`.
  Одним механизмом закрываются оба случая: переигрывание задачи из-за `acks_late` и «пять
  комментариев подряд в один тред → одно письмо».
  **Инвариант выбора `entity_id`:** для событий генерации (`lesson_ready`, `quiz_generated`)
  это **id Celery-задачи**, а не id урока. Celery сохраняет id при redelivery по `acks_late` и
  при retry, поэтому переигранный прогон схлопывается, а новая перегенерация — это новый
  прогон и новое письмо. С `lesson_id` в этой роли повторная генерация того же урока внутри
  окна дедупа молча проглатывалась (поймано вживую 2026-08-26).
- **Гейт присутствия.** `progress_stream` на время жизни SSE-соединения держит своего члена в
  sorted set `notify:presence:lesson:{id}` (member = id соединения, score = последний heartbeat),
  обновляет его на каждом heartbeat и снимает в `finally`. Sorted set, а не флаг: две вкладки —
  два члена, поэтому закрытие одной не снимает присутствие; соединение, оборванное без штатного
  закрытия, само выпадает по score. Активное присутствие означает, что событие **не
  отправляется вообще** — откладывать в дайджест бессмысленно, это тот же шум через полчаса.
  **Два инварианта, без которых гейт не работает вовсе.** (1) Пайплайн ставит уведомление в
  очередь ДО `_publish` терминального события: стрим на этом событии закрывается, а гейту нужен
  ещё живой стрим. (2) Стрим, доживший до терминального события, **не** снимает своего члена в
  `finally` — тот истекает по `NOTIFY_PRESENCE_TTL_SECONDS`. Иначе ZREM срабатывает за
  доли секунды до того, как таск прочитает ключ (publish→zrem ~1 мс против ~100 мс на подхват
  таска), и гейт не срабатывает никогда. Клиент, ушедший раньше срока, по-прежнему чистится
  сразу — иначе закрытая вкладка глушила бы письмо. Регрессия:
  `tests/integration/test_notification_presence_gate.py`.
- **Настройки и отписка.** Три булевы колонки на `User` (по одной на категорию, дефолт — всё
  включено), новых моделей нет. Публичный `/api/v1/notifications/unsubscribe` принимает
  подписанный `itsdangerous`-токен той же схемы, что и верификация почты, со своей солью; токен
  несёт только `{uid, cat}` и не может ничего, кроме как выключить одну категорию своему
  владельцу. GET — для клика человеком, POST — для `List-Unsubscribe-Post` (RFC 8058); оба
  идемпотентны. Все письма подсистемы несут `List-Unsubscribe` и `List-Unsubscribe-Post`.
- **Auth-письма через подсистему не идут.** Верификация почты и сброс пароля остаются прямыми
  `send_email.delay(...)` из `routers/auth.py`: они транзакционные и обязаны уходить независимо
  от любых настроек. `send_email` и его вызовы не менялись — добавился только необязательный
  параметр `headers`.

**Альтернативы:**

- *Прямые `send_email.delay(...)` по месту.* Отвергнуто: ровно та схема, которая породила
  задачу. Шесть точек вызова = шесть мест, где можно забыть проверку отписки, дедуп и гейт
  присутствия, и шесть шаблонов вместо двух.
- *Отдельная таблица уведомлений + in-app inbox.* Даёт историю, счётчик непрочитанных и
  переживает перезапуск Redis. Отвергнуто в этой итерации: требует модели, миграции, роутера,
  фронтового виджета и своего GC — при том что продукт просил письма, а не ленту. Накопитель
  дайджеста живёт минуты-часы, а не вечно, поэтому Redis для него достаточен; путь к inbox
  открыт — реестр событий уже есть, добавится второй sink.
- *Внешний сервис рассылок (Customer.io / Mailchimp-подобное).* Отвергнуто: новая внешняя
  зависимость и вынос логики гейтов за пределы приложения при том, что провайдер отправки
  (Resend) уже есть, а «кому и когда» всё равно знает только наш бэкенд.

**Trade-offs:**

- − Дайджест живёт только в Redis: перезапуск с потерей данных теряет ненаправленные события.
  Сознательно — альтернатива это таблица и её GC, см. выше.
- − Флаш обрабатывает `NOTIFY_DIGEST_FLUSH_BATCH` пользователей за тик; остальные ждут
  следующего. Потолок, а не баг: при текущих масштабах недостижим.
- − Пачка событий разных категорий даёт по письму на категорию, а не одно. Так `List-Unsubscribe`
  в письме честно указывает на ту категорию, о которой письмо, — иначе одна ссылка отписки
  врала бы про половину строк.
- − Атомарный поп накопителя (`LRANGE`+`DEL` в одном `MULTI`) — сам себе токен идемпотентности:
  переигранный флаш не найдёт ничего и не отправит дубль. Цена — узкое окно между попом и
  постановкой письма в очередь, в котором смерть воркера теряет дайджест (логируется).
- − Гейт присутствия по `lesson_id`, а не по `user_id`: открытая вкладка другого урока не
  подавит письмо. Это осознанно — иначе параллельные генерации глушили бы уведомления друг
  друга.
- − События по сдаче/треду/оценке не проверяют `visibility_service`: получатель и так сторона
  этой сдачи, скрывать от него нечего. Гейт видимости стоит там, где он действительно нужен —
  в фан-ауте комментариев по студентам курса (`comment_service.notify_students_of_comment`),
  чтобы комментарий к неопубликованному уроку не выдал его существование.

---

## 55. PPTX pre-processing: расширение `wrap="none"` боксов перед LibreOffice (2026-08-26)

**Контекст:** на сгенерированных PNG строки текста наезжали друг на друга, хотя тот же PPTX
в PowerPoint выглядел корректно. PNG становится статичным кадром MP4
(`ffmpeg -loop 1`), поэтому баг вёрстки «запекается» в урок навсегда.

Замер на реальной колоде (11 слайдов, 3 встык стоящих текстбокса по 31.50 pt высотой):

| | `Даты:` | `2023` | `Площадка:` |
|---|---|---|---|
| до | y=104.46..131.72 | y=**128.47..155.73** | y=135.96..163.21 |
| после | y=104.46..131.72 | y=104.46..131.72 | y=135.96..163.21 |

Причина — стечение трёх обстоятельств:
1. руны несут `<a:latin typeface=""/>`; PowerPoint разрешает пустое имя через `lstStyle`
   шейпа, LibreOffice — нет и берёт собственный дефолт;
2. объявленный в `lstStyle` шрифт (`TTPositive-Regular`) коммерческий, его нет ни в образе,
   ни во встроенных в колоду `ppt/fonts/*.fntdata`, — LibreOffice подставляет Noto Sans,
   который шире;
3. LibreOffice **игнорирует `<a:bodyPr wrap="none">`** и переносит строку, при этом не
   растит `spAutoFit`-бокс. Лишняя строка вываливается за границу и приземляется на
   следующий бокс.

**Решение:** [video_service.py:_prepare_pptx_for_libreoffice](../backend/app/services/video_service.py)
перед конвертацией пишет temp-копию PPTX, в которой у каждого шейпа с `wrap="none"`
расширен `a:ext/@cx`. В PowerPoint-семантике это no-op — `wrap="none"` и так значит «никогда
не переносить», — а LibreOffice лишается повода перенести. Конвертируется копия
(`_prepared/<исходное имя>`), оригинал не трогается: `_pptx_cache_key` по-прежнему считается
от его байтов (инвариант §20). Множитель — `NOWRAP_WIDEN_FACTOR = 2.0` в `constants.py`;
намеренно грубый, потому что итоговый шрифт выбирает fontconfig и точный расчёт ширины
текста всё равно был бы гаданием.

Направление роста следует выравниванию, чтобы отрендеренный текст не поехал:

| `algn` | как растёт |
|---|---|
| `l` (и дефолт) | вправо, `x` не меняется |
| `r` | влево, правый край закреплён, `x` клэмпится в `>= 0` |
| `ctr` | симметрично вокруг **своего** центра (не центра слайда), клэмп с обеих сторон |

Выравнивание берётся из абзацев, а если ни один его не задаёт — из `lstStyle/lvl1pPr`
(реальные колоды объявляют его именно там). Смешанное выравнивание трактуется как `l` —
единственное направление, которое заведомо не двигает видимый текст.

**Деградация:** сбой на одном шейпе логируется (`nowrap_widen_shape_failed`) и не роняет
презентацию; бокс, уже упёршийся в край слайда, логируется как `nowrap_widen_no_room` —
молча не пропускается; любой сбой открытия/сохранения возвращает нетронутый оригинал.
Правка вёрстки не должна быть причиной, по которой урок не сгенерировался.

**Альтернативы:**
- **Распаковывать встроенные `ppt/fonts/*.fntdata`.** Отклонено: это EOT, а не голый TTF
  (magic — LE-размер файла), нужен разбор обёртки; и на разобранной колоде это всё равно не
  помогло бы — нужного `TTPositive-Regular` во встроенных нет, только `TTPositive-Bold`.
  Оставлено как техдолг, см. KNOWN_PROBLEMS.
- **Разрешать пустой `typeface=""` через `lstStyle` самим.** Чинит пункт 1, но упирается в
  пункт 2: LibreOffice начнёт запрашивать шрифт, которого всё равно нет.
- **Только шрифтопак.** Не покрывает приватные коммерческие шрифты клиентов — см. §56, это
  отдельная мера про другую причину и другие колоды.

**Ограничение:** обрабатываются шейпы верхнего уровня; текст внутри групп и таблиц не
трогается (у групп своя система координат через `chOff`/`chExt`).

---

## 56. Шрифтопак в образе + телеметрия недостающих шрифтов (2026-08-26)

**Контекст:** отдельная от §55 проблема с другими колодами. Шрифт, который LibreOffice не
может разрешить, подменяется молча, а метрики подстановки меняют раскладку текста. Проверка:
на колоде со встроенными Open Sans / Merriweather `pdffonts` показывал только
`NotoSans-Regular` + `NotoSans-Bold` — встроенные в PPTX шрифты LibreOffice не читает и
резолвит по **имени** через fontconfig.

**Решение:** статические `.ttf` в [backend/fonts/](../backend/fonts/) (Montserrat, Open Sans,
Merriweather — все под OFL 1.1), `Dockerfile` копирует их в `/usr/local/share/fonts` и гонит
`fc-cache -f`. Плюс телеметрия: [video_service.py:_log_missing_fonts](../backend/app/services/video_service.py)
перед конвертацией собирает все `<a:latin|cs|ea typeface>` из слайдов/лейаутов/мастеров/темы,
сверяет с `fc-list` и пишет `warning` со списком. Это **не фикс**, а видимость — чтобы состав
шрифтопака рос по фактам из логов, а не наугад. На разобранной колоде даёт:
`pptx_fonts_missing count=9 fonts=['Calibri', 'Calibri Light', 'TT Norms Pro', …]`.

**Только статические начертания.** LibreOffice рендерит *variable*-шрифт первым именованным
инстансом: `Montserrat[wght].ttf` → Thin, `Merriweather[opsz,wdth,wght].ttf` → Light. Это хуже
той подстановки, которую шрифтопак должен был заменить, поэтому variable-сборки из
`google/fonts` использовать нельзя.

**Альтернативы:**
- **Debian-пакеты.** Ни `fonts-montserrat`, ни `fonts-open-sans`, ни `fonts-merriweather` в
  base-образе недоступны.
- **Алиасы fontconfig на уже установленное.** Метрики всё равно не совпадут, а именно они
  переливают текст, — то есть проблема не решается, только маскируется.
- **Скачивание шрифтов на этапе сборки.** Отклонено: сеть в билде = невоспроизводимый образ;
  3.4 МБ в репозитории дешевле.

---

## 57. Глубина раскрытия темы вместо целевой длительности (2026-08-27)

**Контекст:** первая итерация давала преподавателю задавать **целевую длительность** урока
(сначала набор 5/10/15/20/30, потом произвольные минуты), а бюджет слов считался как
`target × WPM / слайды`. Практика этот подход сломала. На деке из 3 слайдов цель 15–20 мин
даёт 578–1083 слова на слайд; получив такой бюджет, `qwen2.5vl` перестал писать и ушёл в
цикл из полноширинной CJK-пунктуации (`Представьте себе ， ， ， —— " "`). Пришлось вводить
потолок на слайд, а за ним — предупреждение «цель недостижима». Получился параметр, который
преподаватель задаёт, а система в половине случаев отказывается выполнять.

**Решение:** длительность перестала быть **входом** и стала **следствием**. Преподаватель
выбирает `lessons.detail_level` — `brief` / `auto` / `high` (`DetailLevel`, NOT NULL,
default `auto`), то есть насколько подробно LLM разбирает каждый слайд.
`DETAIL_LEVEL_BODY_WORDS` = {brief: 120, auto: 225, high: 400} — бюджет слов на один
**содержательный** слайд; `auto` совпадает с дефолтом системного промпта (150–300), `high` —
тот самый потолок, за которым модель ломается. Титульный и заключительный слайды получают
`EDGE_SLIDE_BUDGET_WEIGHT` (0.4) от этой доли.

Сколько получится минут — считает `duration_service.expected_duration_sec(level, slides)` и
показывает **рядом с каждым вариантом** ещё до запуска. Никаких недостижимых целей и
предупреждений о них больше нет: любой выбор выполним по построению, а длину урока
регулирует пара «глубина × размер деки».

**Тарификация следует за объёмом.** `estimate_video_auto` и `estimate_vision_analyze`
считают ожидаемый объём как `slides × AUTO_CHARS_PER_SLIDE × detail_ratio(level)`, а
`estimate_video_text` — как `script_chars × detail_ratio(level)`: сжатый текст озвучивается
дешевле, дополненный дороже. `duration_service.detail_ratio` — единственный источник этого
коэффициента, его же получает промпт, поэтому цена и объём не могут разойтись.
Уровень `auto` умышленно попадает в историческую норму символ-в-символ, поэтому дефолтный
сценарий стоит ровно столько же, сколько до появления фичи, а платят больше только за
осознанно более подробный урок. Триал free-плана сверяет ожидаемый объём с
`TRIAL_MAX_SCRIPT_CHARS` — иначе `high` превращал бесплатный слот в безлимит на TTS.

Вырожденный ответ модели **детектируется и перезапрашивается**:
`vision_analysis._looks_degenerate` смотрит на долю буквенных символов
(`MIN_NARRATION_LETTER_RATIO`), потому что такой ответ непустой и проходит все остальные
проверки. Ретрай ровно один и **без бюджета**. Если и он вырожден, слайд отдаётся пустым:
пайплайн падает только когда пусты все слайды.

Выбор применяется на этапе **анализа презентации**, а не генерации видео: в auto-режиме
`generate-video` переиспользует уже написанные `SlideText`. Поэтому селектор стоит на шаге
«Презентация» перед кнопкой анализа, и UI предупреждает, что после смены нужен повторный
анализ.

**Manual-режим (`presentation_and_text`) использует те же три уровня, но применяет их к уже
написанному тексту:** `auto` — озвучить дословно (исторический контракт, ничего не меняется),
`brief` — сжать до главной сути, `high` — дополнить пояснениями и примерами. Реализовано как
override-секция к `_SSML_SYSTEM` (`_SSML_DETAIL_OVERRIDE` в `llm_service.py`): базовый промпт
запрещает переписывание, поэтому override **явно называет правило, которое отменяет**, —
дописать противоречащую инструкцию, не сказав, какое правило проигрывает, значит получить
неоднозначный промпт. Для `auto` override отсутствует физически, а не «пустой»: дефолт
обязан оставлять авторский текст нетронутым, и тест это фиксирует сравнением промпта с
`_SSML_SYSTEM`. Модель получает не «короче/длиннее», а конкретное число слов
(`len(script.split()) × detail_ratio`).

Границы у переписывания жёсткие и заданы промптом: `brief` сокращает **собственные
предложения автора**, сохраняя все факты, термины, числа и выводы; `high` достраивает вокруг
авторских предложений, не имея права противоречить автору или вводить факты, даты, имена и
ссылки, не выводимые из исходного материала. Сам `lesson.script` при этом не меняется —
переписывание живёт только в озвучке, так что откатиться можно переключением на `auto`.

**Альтернативы:**
- **Целевая длительность (первая итерация).** Отклонена по причине выше: параметр,
  который система не может выполнить на короткой деке, — обещание, а не настройка.
- **Подгонять длительность скоростью TTS.** Отклонено с самого начала: ускоренная речь
  читается как дефект, работает только у Yandex-провайдера (`silero`/`polza` игнорируют
  `speed`, см. §15) и маскирует настоящую проблему — неверный объём текста.
- **Итеративная догенерация до попадания в целевую длину.** Цикл LLM-вызовов на каждый
  слайд умножает стоимость и латентность ради точности, которой никто не просил.
- **Запретить переписывание авторского текста в manual-режиме.** Была первая итерация
  («авторский текст не трогаем никогда»). Пересмотрено: запрет спасал от молчаливой правки,
  но этого же результата достигает дефолт `auto`, который дословен. Переписывание стало
  осознанным выбором преподавателя, а не поведением по умолчанию.

**Trade-offs:** три уровня вместо числа — это потеря точности: между `auto` (~19 мин на 12
слайдах) и `high` (~33 мин) промежуточного значения нет. Сознательно: числовая цель уже была
и не сработала. Темп речи `WORDS_PER_MINUTE = 130` — константа, а не измерение конкретного
голоса (замер на реальной лекции дал ~140), и она продублирована во фронтовом
`useLessonDuration.ts`, чтобы оценка пересчитывалась без запроса к API — синхронизируется
руками. Потолок `high` — одно число на все слайды: слайд с плотной схемой и титульный лист
несут разный объём, но различить их до генерации нечем.

---

## 58. OAuth-вход: PKCE + state в Redis, pending-тикет вместо создания юзера в callback (2026-08-28)

**Решение.** Вход и регистрация через Google и Яндекс ID по Authorization Code + PKCE.
Никаких `authlib`/`social-auth` — `httpx` + stdlib (`secrets`, `hashlib`, `base64`), весь протокол
это два POST/GET к провайдеру и один SHA-256. Сетевой обмен — синхронно внутри запроса на async
`httpx`, Celery тут не участвует. Код: [services/oauth_service.py](../backend/app/services/oauth_service.py),
роутер тонкий ([routers/oauth.py](../backend/app/routers/oauth.py)).

**Почему PKCE, если у нас confidential-клиент с секретом.** Секрет и так есть, но PKCE закрывает
кражу authorization code на обратном пути (вредоносное расширение, история браузера, реферер,
логи прокси): без `code_verifier` перехваченный `code` не обменивается. Стоимость — 3 строки.
`state` — отдельная сущность и хранится **в Redis**, а не в куке: кука на redirect-домене
провайдера ходит с `SameSite=Lax` неустойчиво, а Redis у нас уже единственное хранилище сессионного
состояния (refresh-семейства, blacklist, email-токены). Ключ `oauth:state:{state}` потребляется
атомарно через `GETDEL` — повторный, просроченный или чужой `state` просто ничего не находит и
даёт `reason=invalid_state`. Туда же кладётся `code_verifier`, `remember_me` и `next`, поэтому
между `/start` и `/callback` не бегает никакого клиентского состояния.

**Почему pending-тикет, а не создание пользователя прямо в callback.** У нас регистрация — это не
только почта: нужны **роль** (teacher/student) и **обязательные согласия 152-ФЗ** с фиксацией
`pdn_consent_at`, `consent_policy_version`, `consent_ip`. Провайдер не даёт ни того, ни другого.
Создать юзера в callback можно было бы только с догадкой о роли и с непроставленным согласием —
то есть с юридически пустой записью, которую потом нечем починить. Поэтому ветка C кладёт
одноразовый тикет в `oauth:pending:{ticket}` (TTL 10 мин) и отдаёт SPA на `/register?oauth_pending=…`,
где та же форма (те же галочки, тот же тумблер роли) добивает регистрацию через
`POST /auth/oauth/complete`. Тикет сжигается тем же `GETDEL`, поэтому две вкладки, дожавшие один
тикет, дадут ровно одного пользователя — второй получит 400 `invalid_ticket`.

**Почему почта от провайдера считается подтверждённой.** `email_verified` у нас — доказательство
владения ящиком, и цель письма-верификации ровно эта. Google и Яндекс уже провели ту же проверку,
причём строже; слать своё письмо поверх чужого подтверждения — это просить пользователя доказать
то, что он только что доказал. Поэтому OAuth-аккаунт сразу проходит `require_verified_email` /
`require_verified_teacher`. Google при этом проверяется явно: без `email_verified=true` в userinfo
вход отклоняется (`reason=email_unverified`) — у Google бывают аккаунты с неподтверждённым адресом.

**Допущение по Яндексу.** `login.yandex.ru/info` **не отдаёт** признака подтверждённости адреса:
есть `default_email` и `emails[]`, флага нет. Принято считать `default_email` подтверждённым —
Яндекс ID заводится на ящик, которым владеет пользователь, а внешние адреса в аккаунт добавляются
только после подтверждения. Это осознанное допущение, а не недосмотр: если Яндекс когда-нибудь
начнёт отдавать неподтверждённые адреса, ветка B (линковка по совпадению почты) станет вектором
захвата чужого аккаунта — тогда нужно либо запросить подтверждение письмом для яндексовой ветки,
либо запретить ей ветку B. Ограничение записано в `_parse_profile` рядом с кодом.

**Почему `hashed_password` стал nullable.** Аккаунт, заведённый только через провайдера, пароля не
имеет. Альтернатива — писать туда случайный «неиспользуемый» хеш — экономит миграцию, но врёт:
по строке нельзя отличить «пароля нет» от «пароль есть»; `change-password` тогда сравнивает ввод с
мусором и отвечает «неверный текущий пароль» вместо честного «пароля нет», а вычислять Argon2 от
случайной строки на каждой регистрации — плата ни за что. NULL — это факт, и он читается прямо:
`login` схлопывает такой аккаунт в обычный **401** (никакой подсказки «этот аккаунт через Google» —
иначе получается оракул перечисления), `change-password` → **400 `password_not_set`**,
`forgot-password` работает как раньше (всегда 204, письмо уходит), а `reset-password` по такому
аккаунту **задаёт** пароль — так у социального пользователя остаётся штатный путь завести
локальный вход, не изобретая отдельного «set-password» эндпоинта.

**Линковка (ветка B) и её граница.** Новая identity с почтой существующего аккаунта линкуется к
нему, а не создаёт дубль — иначе один человек получает два кабинета с разными курсами. Единственный
случай отказа: у аккаунта **уже есть** identity того же провайдера с другим `provider_user_id`
(`reason=account_conflict`). Слияние двух провайдерских аккаунтов в один локальный мы не делаем —
это ручная операция поддержки, а не автоматическая догадка.

**Trade-offs.** `state` и тикет живут в Redis: рестарт Redis рвёт **начатые** входы (пользователь
получает `invalid_state` и жмёт кнопку заново) — приемлемо, там же уже лежат все сессии.
Ветка B доверяет почте провайдера: аккаунт, заведённый по паролю, можно перехватить, если
провайдер отдаст чужой подтверждённый адрес — защита ровно на уровне доверия к Google/Яндексу.
`OAuthAccount.email` хранится как есть на момент линковки и **не** обновляется при смене почты у
провайдера — это аудит-след, авторитетный адрес всегда `users.email`.

---

## 59. Lifecycle аккаунта: soft-delete → restore → освобождение email → обезличивание вместо DELETE; модель аватара (2026-08-29)

**Контекст.** Самоудаления аккаунта в продукте не было вовсе. Хелпер `soft_delete_user` существовал
«на вырост», не имел ни одного продакшн-вызова и делал ровно то, что ломает окно восстановления:
сразу затирал email в `deleted_{uuid}@anon.invalid`. Одновременно понадобился публичный профиль с
аватаром — а профиль сразу упирается в вопрос «что показывать от удалённого пользователя».

### 59.1. Soft-delete больше не обезличивает

`soft_delete_user` теперь ставит только `deleted_at` + `is_active=False`. Личность (email, имя)
**сохраняется** на всё окно восстановления, потому что от неё зависят три вещи сразу:
восстановление по email+паролю, 409 при повторной регистрации на тот же адрес и осмысленное письмо
«аккаунт удалён». Обезличивание переехало в конец жизненного цикла —
`account_service.anonymize_user_fields`.

Окно восстановления **равно** `SOFT_DELETE_PURGE_DAYS`. Второго таймера нет сознательно: пока строку
нельзя пуржить — её можно восстановить, как только можно пуржить — нельзя. Два независимых срока
неизбежно разъехались бы.

### 59.2. Purge обезличивает, а не удаляет — продолжение §51

`purge_soft_deleted` для юзера старше окна теперь имеет **три** исхода, а не два
(`_user_purge_guard`): строка занята/восстановлена → пропустить; на юзере висят учебные данные
(свои `Enrollment` либо студенты на его курсах) → **обезличить и оставить**; пусто → как раньше,
физический DELETE.

Причина ровно та же, что в §51, и там же записана в trade-off'ах как незакрытая: цепочка
`users → courses → modules → lessons → enrollments/lesson_progress` (+ попытки квизов и сдачи) вся
объявлена `ondelete=CASCADE`, поэтому хард-удаление преподавателя стирало **чужие** оценки, а
хард-удаление студента — строки, по которым преподаватель выставлял эти оценки. Право на удаление
данных удовлетворяется уничтожением персональных данных, а не уничтожением чужой истории. §51 в
этой части закрыт.

`anonymize_user_fields` — **чистая** функция: мутирует поля, не трогает ни сессию, ни хранилище.
Иначе её нельзя было бы звать из обоих путей: async-сервис (`confirm-release`) и строго sync
Celery-таск (purge) не могут делить сессию. Удаление файла аватара — отдельным шагом рядом с каждым
вызовом. Идемпотентность проверяется по tombstone-адресу (`is_anonymized`), а не флагом-колонкой:
адрес детерминированно выводится из `user.id`, поэтому повторный прогон ничего не переписывает.

Побочный эффект, найденный тестом: `verify_password` ловил только `VerifyMismatchError`, поэтому
неиспользуемый хеш обезличенного аккаунта ронял `InvalidHashError` → 500 на логине. Починено в
общей функции — «не могу проверить» это провал проверки, а не 5xx.

### 59.3. Освобождение email — по письму, не по паролю

Пока идёт окно, адрес занят и регистрация отвечает **409** с кодом `account_pending_deletion`
(новой утечки нет — этот эндпоинт и так раскрывал существование 409-м). Владельцу ящика нужен путь
забрать адрес раньше срока, и подтверждать он должен **владение ящиком**, а не знание пароля: пароля
он может не помнить, а восстановление здесь как раз не нужно. Поэтому `release-email` всегда
отвечает **204** (иначе это оракул существования), а ссылка из письма ведёт на `confirm-release`,
который обезличивает немедленно.

После этого восстановление невозможно **по построению, а не по флагу**: хеш пароля и email — ровно
те два поля, по которым матчатся оба пути restore — уничтожены. Гонка «release и restore
параллельно» закрыта перечитыванием `deleted_at` внутри `confirm-release`: если владелец успел
восстановиться, ссылка отдаёт 400 и живой аккаунт не обезличивается.

Оба токена — stateless `itsdangerous` со **своими солями** (`account-restore`, `email-release`), по
образцу верификации почты и отписки; новых таблиц нет. Соли разные не для красоты: restore-ссылка
обратима, release-ссылка уничтожает аккаунт, и подмена одной другой недопустима (зафиксировано
тестом). Одноразовость release — Redis `SET NX`, тот же burn, что у верификации.

**Альтернативы.** *Хард-удалять сразу, без окна* — самый частый сценарий поддержки «удалил случайно»
становится необратимым. *Отдельная таблица токенов* — миграция ради двух ссылок, которые и так
подписаны. *Держать адрес занятым все 30 дней без выхода* — реальный пользователь, решивший начать
заново сегодня, упирается в стену на месяц. *Освобождать по паролю* — не работает для того, кто
пароль забыл, а это и есть типичный случай.

### 59.4. Аватар: загруженный + внешний, и почему файл не гейтится приватностью

На `User` пара колонок по образцу обложки курса: `avatar_image_path` (загруженный файл) и
`avatar_external_url` (URL от провайдера). В ответе — одно вычисляемое `avatar_url`, загруженный
выигрывает. Отдельного enum-переключателя «чей аватар показывать» нет: «вернуть аватар Google» — это
просто `DELETE` загруженного. Третье состояние, которое нужно синхронизировать с двумя колонками,
это лишний способ рассинхронизироваться.

`avatar_external_url` принимается только с allowlist хостов (`lh3.googleusercontent.com`,
`avatars.yandex.net`) и только по `https`. Внешний аватар отдаётся фронту как есть и **не
проксируется** через бэкенд — проксирование это SSRF-поверхность и лишний трафик ради картинки.
Значение перезаписывается при **каждом** входе провайдером: картинка на той стороне могла смениться,
а очистка при её пропаже так же осознанна.

Загруженный файл всегда **перекодируется** (Pillow уже в зависимостях — новая не нужна):
`exif_transpose` → `ImageOps.fit` в квадрат → WEBP. Перекодирование и есть механизм **вырезания
EXIF**: `save()` не пишет EXIF, если его не передать, поэтому геометка из телефона до хранилища не
доезжает. Один выходной формат — одно расширение и тривиальное удаление. Замена аватара сносит весь
префикс `avatars/{user_id}/` перед записью, поэтому сирот не остаётся by construction — нет
бухгалтерии «старый путь», которую можно рассинхронизировать.

**Файл аватара не гейтится приватностью профиля** — осознанное решение. Подписанный URL несёт `uid`
владельца, но `uid` в `signed_url_service` входит только в HMAC-payload и **не является проверкой
доступа** (`routers/files.py` сверяет подпись, а не личность запрашивающего), поэтому ссылка
работает и у анонима. Альтернатива — проверять приватность на каждом запросе картинки — ломает
кеширование и раздачу `/files/*` напрямую nginx'ом в проде (nginx о приватности ничего не знает), и
всё это ради данных, которые пользователь и так сам загрузил как своё публичное лицо. Скрывается
профиль, а не аватар.

SVG в whitelist отсутствует: это скриптовый документ, а `/files/*` отдаёт его инлайном — то есть
хранимый XSS. Заодно закрыта дыра пошире: у `_check_magic` **вообще не было ветки для изображений**,
поэтому SVG, переименованный в `.png`, проходил валидацию. Ветка добавлена в общую функцию, а не в
аватарный роутер.

### 59.5. Приватность профиля

Три режима (`public | authenticated | private`), дефолты по роли: преподаватель — открытый профиль
со статистикой (его профиль это витрина, на которую приходит будущий студент), студент —
`authenticated` без статистики (его прогресс никого по умолчанию не касается). Недоступный профиль
отдаёт **404, а не 403** — консистентно с правилом «черновик → 404»: API не должен подтверждать, что
скрытый аккаунт существует. `show_profile_stats=false` вырезает **только числа**; личность, аватар и
список курсов остаются — иначе это не «скрыть статистику», а «скрыть профиль», и режим дублировал бы
`private`. Владелец видит свои числа всегда. Исключение из `private` — преподаватель курса, на
который студент записан: иначе преподаватель перестал бы видеть собственный ростер.

Приватность — контур чтения **только этого ресурса**. Журнал оценок, аналитика курса и preview не
затронуты: преподаватель по своим курсам видит всё как раньше.

### 59.6. `CourseOut.owner` стал опциональным

Глобальный soft-delete фильтр скрывает удалённого преподавателя, поэтому `Course.owner` грузится как
`None` — раньше это было недостижимо, теперь достижимо и в grace-окне, и **навсегда** после
обезличивания (строка остаётся `deleted_at IS NOT NULL`). Взят вариант, предложенный самим
KNOWN_PROBLEMS: `owner: UserOut | None`. Вторая альтернатива оттуда — каскадно архивировать курсы
удаляемого преподавателя — отвергнута: она отзывает доступ у записанных студентов, то есть прямо
противоречит §51. Фронт рисует «Удалённый пользователь» + инициалы, ссылка на профиль ведёт в 404.

**Trade-offs.**

- **+** Удаление аккаунта не уничтожает чужие оценки; §51 закрыт симметрично для User.
- **+** Один рычаг срока (`SOFT_DELETE_PURGE_DAYS`) вместо двух расходящихся.
- **+** EXIF не доезжает до хранилища; SVG-XSS закрыт на общем пути валидации, а не в одном роутере.
- **−** Обезличенные строки копятся навсегда: у активной платформы каждый удалённый аккаунт с хотя бы
  одним enrollment остаётся строкой в `users`. Это цена за сохранность чужих данных, та же, что за
  вечное хранение курсов с записями в §51.
- **−** Восстановление доступно и тому, кто удалил аккаунт со скомпрометированной сессии: смягчено
  тем, что restore требует пароль либо доступ к почте, а письмо об удалении уходит немедленно.
- **−** `avatars/` не попадает под `gc_disk_caches` (как и оба TTS-кеша): осиротеть файл может только
  при падении между `delete_prefix` и `save_bytes`, но автоматической подчистки нет.

## 60. Клиентский кулдаун после 429 на /auth/register и /auth/login (2026-08-30)

`rate_limit_exceeded_handler` в `main.py` отвечает на `RateLimitExceeded` голым `JSONResponse(429, ...)`
без заголовка `Retry-After` — slowapi его не проставляет автоматически, а хендлер написан вручную и
заголовок не добавляет. Фронт (`useRateLimitCooldown.ts`) читает `Retry-After`, если он появится в
будущем, но по факту сегодня всегда уходит в фолбэк — фиксированные 30 секунд, — и на это время
блокирует повторный сабмит формы (кнопка задизейблена, показан обратный отсчёт).

Альтернатива — вычислять точный остаток окна (`3/minute` для register, `5/minute` для login) на
клиенте — отвергнута: slowapi считает лимит по скользящему окну в Redis/памяти воркера, у клиента нет
доступа к этому счётчику, а повторять его логику ради подсказки в секундах — сложность ради
косметики. Фолбэк не обязан быть точным: он не заменяет серверный лимит (тот всё равно применяется
per-IP), а только не даёт пользователю жать «Войти» в тот же лимитируемый минутный интервал ещё раз
вхолостую.

**Trade-offs.**

- **+** Один компонуемый composable на оба флоу (`register.vue`, `login.vue`), а не дублирование таймера.
- **+** Готов к серверному `Retry-After`, если он появится — правка в одном месте (`main.py`), фронт
  подхватит без изменений.
- **−** Фолбэк-кулдаун (30 с) не совпадает с реальным остатком окна slowapi (до 60 с для register).
  Пользователь может дождаться конца кулдауна и всё равно получить второй 429 — в этом случае
  `triggerFrom429` просто перезапускает тот же таймер.

## 61. Текстовый урок: тело в `Lesson.text_content`, inline-вложения — те же `LessonMaterial`, ссылка `material:{uuid}` вместо подписанного URL (2026-08-31)

**Контекст.** К видео-уроку и загруженному видео добавился третий тип — чисто текстовый урок
(`content_type = "text"`) с markdown-телом, которое преподаватель пишет прямо в кабинете: с
картинками в потоке текста и вложениями между абзацами. Параллельно закрывался разрыв в базе знаний
(§47): файлы, которые преподаватель заливал через `/uploads/pptx` и `/uploads/script`, в базу знаний
не попадали, а сама база знаний существовала только на уровне одного урока.

Три развилки требовали решения до кода: где живёт тело урока, чем помечается inline-роль материала и
что именно пишется в markdown на месте картинки.

**Решение.**

*Тело урока — существующая колонка `Lesson.text_content`, новой сущности нет.* Enum `content_type`
уже содержал `'text'` с самой первой миграции (`c2f900c2bf7a_init_schema`), а `text_content` уже был
объявлен как nullable `Text` и уже отдавался в `LessonOut` — обе половины типа лежали в схеме
неиспользованными. Отдельная таблица не даёт ничего: тело ровно одно на урок, версионирование не
требуется, а FK-каскад `lessons → …` и так уносит его при удалении урока. Единственная правка схемы
во всей задаче — булев флаг на материалах.

Записывается тело ТОЛЬКО через `PUT /lessons/{id}/text` (`LessonTextUpdate` → `save_text_body`).
`text_content` намеренно **удалён** из `LessonUpdate`: сохранение тела попутно подчищает inline-
материалы, на которые в новом тексте не осталось ссылок, и второй вход в то же поле молча
пропускал бы эту уборку, оставляя сирот в хранилище. Это тот же принцип, что и «одна точка
settle-платежа» в биллинге и «одна точка входа уведомлений» в §54.

*Inline-картинки — те же `LessonMaterial`, отличаются флагом `is_inline`.* Отдельная модель под
картинки в тексте означала бы второй контур валидации, второй префикс в хранилище, вторую строку в
`purge_pipeline` и второй набор лимитов — при том, что содержательно это тот же «файл, приложенный к
уроку, который сервер никогда не парсит». Флаг делит только представление: inline-файлы не попадают
в список «Файлы» и являются кандидатами на уборку сирот. Всё остальное — whitelist
`LESSON_MATERIAL_EXTENSION_MIME` → `validate_upload` (magic-байты, zip-slip/zip-bomb) →
`save_upload_bounded`, префикс `materials/{lesson_id}/`, ночной purge, удаление объекта перед
строкой — общее. `LESSON_MATERIAL_MAX_INLINE_FILES` (20) — подлимит ВНУТРИ лимита урока (30 файлов /
2 ГБ), а не параллельный ему.

*В markdown хранится `material:{uuid}`, а не подписанный URL.* Ссылки на материалы подписываются HMAC
и живут `SIGNED_URL_TTL_MATERIAL` = 15 минут. Записать такой URL в тело — значит гарантированно
получить битую картинку через четверть часа после сохранения, навсегда: тело статично, а подпись
протухает. Поэтому в тексте лежит только идентификатор, а конкретный URL резолвится на рендере из
карты материалов урока, которую клиент уже получил (`GET /lessons/{id}/knowledge`) — лишнего запроса
не возникает. Схема `material:` добавлена в whitelist рендерера третьей, рядом с http(s) и mailto;
резолв идёт ТОЛЬКО по карте текущего урока, поэтому uuid чужого урока или удалённого материала
превращается в обычный текст — не в битую ссылку и не в запрос.

*Авто-регистрация загрузок делает собственную копию и дедупится по имени и размеру.* `/uploads/pptx`
и `/uploads/script` после основного сценария зовут `register_uploaded_file`, который НИКОГДА не
бросает: исчерпанный лимит урока или расширение вне whitelist материалов (например `.html`, годный
как источник скрипта, но не как материал) — это пропуск с записью в лог, а не проваленная загрузка.
Копия кладётся своя, под `materials/{lesson_id}/`, а не переиспользуется объект пайплайна: иначе
«удалить материал» тихо ломало бы генерацию видео, а ночной purge, который метёт именно этот
префикс, не достал бы файл под `pptx/`. Дедуп — по `(lesson_id, original_filename, size_bytes)` со
**пропуском**, существующая строка не трогается.

**Альтернативы.**

- *Отдельная таблица `LessonTextBody`* — отвергнута: одна запись на урок, никакого выигрыша над уже
  существующей колонкой, плюс миграция и re-export в `models/__init__.py` ради нуля пользы.
- *Подписанный URL прямо в markdown* — отвергнута: тело статично, подпись живёт 15 минут.
- *Отдельная модель `LessonInlineImage`* — отвергнута: дублирование всего контура валидации,
  хранения и purge ради одного булева различия в UI.
- *Дедуп по хешу содержимого* — отвергнут: требует новой колонки И чтения байтов обратно из
  хранилища (в том числе с S3), тогда как реальный дубль — это повторная заливка того же файла в тот
  же урок, которую имя+размер ловят без единого лишнего чтения.
- *Дедуп по storage-пути* — отвергнут как неработающий: `save_upload` генерирует уникальное
  uuid-имя на каждый вызов, поэтому совпадения пути не бывает никогда.
- *Репойнт существующей строки на новый объект при совпадении* — отвергнут: он вносит удаление из
  хранилища в путь загрузки, который по контракту не должен падать; молча подменяет содержимое под
  ссылкой, уже отданной студенту; и затирает title/description, если преподаватель правил их руками.
- *WYSIWYG-редактор и markdown-библиотека на фронт* — отвергнуты: у проекта свой рендерер на VNode
  (без `v-html`) именно чтобы пользовательский ввод не мог стать разметкой; новая зависимость этот
  инвариант размывает.
- *Второй роутер под `/courses/{id}/knowledge`* — отвергнут: три роутера уже делят префикс
  `/api/v1/lessons`, и одинаковые пути там молча затеняются порядком регистрации. Хендлер положен в
  `courses.py`, логика — тот же вызов сервиса.

**Trade-offs.**

- **+** Изменение схемы — одна булева колонка; типы уроков, миграции enum и новая сущность не нужны.
- **+** Один рендерер на конспекты и на тело урока; ни одного нового `v-html`.
- **+** Просроченная подпись картинки чинится сама (singleflight-рефетч карты материалов), как и у
  плеера с видео.
- **−** Авто-регистрация удваивает расход лимита урока: PPTX лежит и под `pptx/`, и под
  `materials/{lesson_id}/`. Осознанная цена за то, что удаление материала не ломает генерацию.
- **−** Дедуп по имени+размеру не различает файлы с одинаковым именем и размером, но разным
  содержимым: второй не зарегистрируется, в базе знаний останется первый.
- **−** Дерево базы знаний курса отдаётся целиком, без пагинации (тела конспектов исключены, но
  метаданные материалов — нет). См. `KNOWN_PROBLEMS.md`.
- **−** Осиротевшие inline-материалы подчищаются только при сохранении тела. Урок, у которого тело
  ни разу не пересохраняли после удаления картинки из текста, держит файл до purge урока.

## 62. Избирательный доступ к курсу: режим `invite` поверх существующего `access_mode`, гранты как отдельная таблица (2026-08-31)

**Контекст.** Единственным способом попасть на курс была самозапись по `Course.access_code` (`POST /students/enroll`). Преподавателю нужен второй сценарий: курс, на который попадают только явно выбранные студенты — по профилям уже зарегистрированных пользователей.

**Решение.**

1. **Не заводить второй флаг режима.** `Course.access_mode` уже существует с 
   init-схемы: `AccessMode(link | code | invite)`, где `invite` был объявлен в 
   enum, но **не использовался нигде в коде**. Он и стал режимом «по списку»:
   `link`/`code` — открытые (поведение не изменилось), `invite` — restricted.
   Альтернатива (отдельная колонка `access_mode_v2 = open|restricted`) давала бы
   две почти одинаковых оси на одной сущности плюс `ALTER TYPE ... ADD VALUE`,
   который alembic autogenerate всё равно не видит. Наружу режим отдаётся
   вычисляемым булевым полем `CourseOut.access_restricted`, чтобы клиенту не
   приходилось знать, что «restricted» пишется как `invite`.
2. **Гранты — отдельная таблица `course_access_grants`**, а не колонка на
   `Enrollment`. `UNIQUE(course_id, student_id)`, `granted_by_id` для аудита.
   Отзыв гранта — удаление строки; `Enrollment`, `LessonProgress`, оценки и
   сдачи остаются, поэтому журнал преподавателя не теряет историю. Обратная
   сторона: студент, у которого отозвали доступ, продолжает висеть в журнале —
   это осознанно, «убрать из списка» ≠ «стереть результаты».
3. **Правило доступа — одна функция.** `services/course_access_service.py`:
   доступ = `Enrollment` существует **И** (курс открыт **ИЛИ** есть грант).
   Функция даёт две формы одного правила — `get_enrollment`/`has_access` для
   точечных гейтов и `access_clause(student_id)` как SQL-фрагмент для списочных
   запросов (`my-courses`, дашборд, списки тестов/заданий), чтобы не городить
   N+1. Это тот же приём, что и `visibility_service`, и слой над ним, а не
   вместо: `course_access_service` отвечает «пустить ли на курс», 
   `visibility_service` — «какие модули/уроки курса опубликованы». AND-правило 
   публикации не тронуто.
4. **Переключение `open → restricted` бэкфиллит гранты** всем, у кого уже есть
   `Enrollment` (один `INSERT … SELECT … ON CONFLICT DO NOTHING`, в той же
   транзакции, что и смена режима) — иначе смена режима молча выкинула бы всю
   группу. Обратное переключение возвращает `code`, если код есть, иначе `link`;
   гранты при этом не удаляются и ни на что не влияют, так что режим можно
   переключать туда-обратно без потерь.
5. **`POST /students/enroll` на restricted-курсе отвечает 403** одинаково при
   верном и неверном `access_code` — код перестаёт быть фактором. Проверка стоит
   до идемпотентной ветки «уже записан», но пропускает студента с грантом, чтобы
   повторный заход на `/join` не ломался.
6. **Добавление студента сразу создаёт `Enrollment`**, если его нет: отдельного
   шага «принять приглашение» нет, преподаватель добавил — студент видит курс.
   Идемпотентность и гонки закрыты `ON CONFLICT DO NOTHING` по обоим UNIQUE, а
   не отловом `IntegrityError`.

7. **Добавление только по точному email; эндпоинта поиска/просмотра студентов
   нет вообще.** Первая версия имела `GET /courses/{id}/access-grants/search`
   с ILIKE по email и ФИО — это был справочник для выкачивания: `q=@gmail.com`
   возвращал десяток чужих адресов с именами, перебором префиксов выгружался
   весь список студентов платформы. Причём это больше, чем отдаёт страница
   профиля, где `profile_service._teaches_student` требует, чтобы студент
   вообще учился у этого преподавателя. Промежуточный вариант (подстрока —
   только по своим студентам, чужие — по полному email) тоже отброшен: если
   незнакомца всё равно ищут по точному адресу, отдельный шаг «поиск» лишний.
   Итог — `search` удалён, `POST /courses/{id}/access-grants` принимает
   `{email}`: нашёлся студент → 201 и он в списке, не нашёлся → 404 «Студент с
   таким email не найден». Одна ручка вместо двух, ноль поверхности для
   перебора. Несуществующий адрес, не-студент и soft-deleted аккаунт отвечают
   **одинаковым** 404, сверху `@limiter.limit("20/minute")`.
   Тест `test_candidate_search_endpoint_is_gone` фиксирует отсутствие поиска,
   чтобы его не вернули не читая этот пункт.

8. **Живое обновление кабинета — SSE поверх Redis pub/sub, плюс рефетч по
   фокусу как страховка.** `GET /api/v1/students/courses/stream`
   (`routers/students.py`) повторяет форму стрима прогресса урока из
   `routers/lessons.py`, но без presence-учёта и без снапшота: восстанавливать
   нечего, клиент на любое сообщение просто перезапрашивает `/my-courses`.
   Канал — `student:{id}:courses`, публикуют выдача и отзыв гранта
   (`course_access_service.publish_access_change`). Публикация **best effort**:
   упавший Redis не должен ронять действие преподавателя, поэтому исключение
   гасится с `logger.warning`.

   Роут объявлен **выше** `/courses/{course_id}` — иначе параметр съедает
   литерал `stream` и отвечает 422; порядок закреплён тестом
   (`test_route_shadowing_guard` ловит только точные дубли, не этот случай).

   Два уровня специально: `useCourseAccessStream` даёт мгновенность,
   `useRefetchOnFocus` — гарантию. EventSource переподключается сам по
   серверному `retry:`, но сдаётся навсегда, если реконнект получил не-2xx
   (что даёт blue-green переключение слотов). Тогда список всё равно
   освежится, когда студент вернётся на вкладку, — поэтому здесь нет
   лестницы бэкоффов, как в `useProgressStream`. Стрим живёт в layout
   `student-cabinet`, а не на страницах: одно соединение на весь кабинет.

**Trade-off'ы.** (а) Три состояния в одном enum вместо двух ортогональных осей: 
режим `invite` «съедает» выбор link/code, поэтому при возврате в open режим 
восстанавливается по наличию кода, а не запоминается. (б) Проверка гранта — 
коррелированный `EXISTS` на каждый student-facing запрос; на текущих объёмах 
дешевле джойна, но при росте потребуется индекс-only скан по 
`uq_course_access_grant_course_student`. (в) **Главное ограничение для «полностью закрытых» курсов:** 
пригласить можно только уже зарегистрированного студента. Автор закрытого курса 
обычно зовёт людей, которых на платформе ещё нет, и получит 404 — им придётся 
сначала зарегистрироваться самим. Следующий логичный шаг, если это станет 
мешать, — pending-инвайт по email, который срабатывает при регистрации; 
сознательно не делаем, пока не подтвердится спрос. (г) Поиск по точному email 
подтверждает, что такой студент на платформе есть — неизбежная утечка любого 
«пригласи по email» потока; принята осознанно, снижена рейт-лимитом. (д) Потолок SSE — пул Redis, 
а не CPU: подписка держит соединение всё время, пока открыта вкладка. Замерено 
на redis-py 5.2.1 с `max_connections=20`: 21-я подписка падает с «Too many 
connections», и следом падает **любая** другая команда в этом воркере — то есть 
толпа стримов уносила бы с собой логин. Сделаны два шага. Первый — pub/sub вынесен на 
отдельный пул (`get_pubsub_redis`, `REDIS_PUBSUB_MAX_CONNECTIONS=100`), обычные 
команды остались на общем (`REDIS_MAX_CONNECTIONS=20`); это ограничило 
блast-радиус самими стримами, но потолок остался. Второй — потолок убран (и попутно обнаружился настоящий: 
`Depends(get_db)` держал соединение с Postgres на всё время стрима, потому что 
request-scoped сессия живёт до конца ответа, а SSE-ответ не заканчивается никогда — 
пул 5+10 высыхал на ~15 стримах, что вдвое хуже редисовского потолка. Оба стрима 
теперь отдают соединение через `await db.close()` сразу после авторизации): 
`services/course_stream.py` держит **одну** подписку `psubscribe('student:*:courses')` 
на процесс и раздаёт события по asyncio-очередям, ключ — id студента. Redis-соединений 
теперь O(воркеров), а не O(вкладок); стрим курсов больше не расходует пул вообще 
(отдельный пул остался нужен стриму прогресса урока в `lessons.py`, который 
по-прежнему подписывается на соединение — он короткоживущий и на урок, а не на 
сессию). Три следствия, которые пришлось заложить в код: **(1)** один читатель на 
всех — если бы он умер, все кабинеты молча замерли бы при живых с виду SSE, поэтому 
он переподписывается с backoff, а не падает; **(2)** `subscribe()` ждёт события 
готовности — иначе изменение, опубликованное сразу после коннекта, попадало бы в 
окно между стартом задачи и реальным `psubscribe`; **(3)** очередь ограничена 
(`COURSE_STREAM_QUEUE_MAXSIZE=16`), переполнение отбрасывается — клиент на любое 
сообщение перезапрашивает весь список, поэтому непрочитанное сообщение уже 
покрывает отброшенные; **(4)** регистрация и снятие подписчика — **синхронные**, 
без лока. Генератор SSE отменяют, когда браузер уходит, и любой `await` в пути 
очистки (например, взятие оспариваемого лока) отменяется вместе с ним: замерено — 
500 отключившихся клиентов оставляли подписку живой бесконечно. Цикл событий 
однопоточный, поэтому мутации dict/set лок не нужен.

   **Нагрузочный замер (dev, один uvicorn-процесс, 500 одновременных стримов):** 
   память +64 МиБ (≈128 КБ на стрим) и стабильна между прогонами (257→258→258 МиБ), 
   CPU без изменений, `PUBSUB NUMPAT` = 1, соединений к Postgres — 6 (не растёт). 
   Оставшееся ограничение — **всплеск переподключений**, а не удержание: рукопожатие 
   берёт соединение из общего пула (`REDIS_MAX_CONNECTIONS=20`) для проверки 
   blacklist'а токена, поэтому 300 коннектов в одну миллисекунду дают часть 500-к, 
   а те же 500 с постепенным подключением проходят без единой ошибки. Актуально 
   после blue-green переключения, когда все вкладки переподключаются разом. (е) Нет автодополнения: чтобы добавить человека, нужно знать адрес целиком, опечатка 
даёт «не найден» без подсказки. Это цена отказа от справочника.

**Связано:** §34 (цепочка публикации), §51 (архивирование не отзывает доступ), 
KNOWN_PROBLEMS §6.4.
