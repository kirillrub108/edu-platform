# ROADMAP — приоритизированный план развития после MVP

> Аудит реальной кодовой базы против докладных кандидатов (KNOWN_PROBLEMS, DECISIONS, ARCHITECTURE §9–10, DEPLOYMENT §7). Каждый пункт сверен с кодом, привязан к `file:line` и помечен статусом. Сгенерировано: **2026-06-15**. Источник истины — **код**; где доклад расходится с кодом, выигрывает код (см. «Документация vs код»).
>
> Метод: 5 кластеров верификации (security / ops / scale / correctness / product), каждый прошёл независимую adversarial-перепроверку (скептик переоткрывал процитированную строку). Полный лог — workflow `edllm-roadmap-audit`.

## Легенда

- **VERIFIED** — подтверждено в коде (цитата `file:line`). **UNVERIFIED** — не удалось подтвердить кодом (указано, что искалось).
- Статус: `open` (проблема в коде есть) · `partial` (частично закрыто, остаток описан) · `resolved` (закрыто — в планах не висит, см. «Что уже сделано») · `outdated-report` (доклад описывает как проблему, код опровергает).
- Оценка **S/M/L** — грубая прикидка трудозатрат, не обязательство.

## Инварианты (фиксы НЕ должны их ломать — из CLAUDE.md)

Async-роутеры и sync Celery-таски не смешивать (greenlet-дедлок) · порядок middleware в `main.py` не менять · auth на httpOnly-куках + double-submit CSRF (не Bearer/localStorage) · стриминг `as_completed` TTS→FFmpeg в `video_pipeline.py` сохранять · новый Celery-таск → маршрутизация в очередь, ровно один beat · тюнинг пайплайна — через `constants.py`/env, не инлайн.

---

## Фаза 0 — Блокеры запуска прода

> **Главный вывод аудита: классических security-блокеров в коде НЕ осталось.** SECRET_KEY, CORS, раздача `/files/*`, парсинг `.docx`, хеширование паролей, rate-limiting, ротация refresh — подтверждённо закрыты (см. «Что уже сделано»). Остаток Фазы 0 — это **операционная конфигурация и одно продуктовое решение**, без которых нельзя пускать реальных пользователей.

| # | Что | Где (`file:line`) | Риск | Фикс | Оценка | Статус |
|---|---|---|---|---|---|---|
| **P0-1** | `SENTRY_DSN` пуст в прод-шаблоне → прод бежит без error-tracking | `backend/app/config.py:174` (`SENTRY_DSN=""`), `.env.prod.example:112` (пусто); init есть в `main.py:56-82`, `celery_app.py:27-49` | Прод вслепую: ошибки FastAPI/Celery никуда не уходят | Заполнить `SENTRY_DSN` в развёрнутом `.env.prod` (код уже умеет — гейтится на непустом DSN) | S | VERIFIED · open (config) |
| **P0-2** | Решение по signed-URL `/files/*`: bearer-style в пределах TTL | `services/signed_url_service.py:32-33` (комментарий «без JWT, для `<img>`), `config.py:163` `SIGNED_URL_EXPIRES_IN=3600` | Утёкшая подписанная ссылка даёт доступ к файлу ~1 ч; `uid` в URL — не авторизация, только HMAC-целостность | Перед запуском с приватным/платным контентом: либо принять (ок для MVP) и задокументировать, либо сократить TTL / привязать к сессии на не-nginx пути. HMAC-схему НЕ ломать | M | VERIFIED · partial → решение |
| **P0-3** | Гигиена `.env.prod` (не регрессировать) | `config.py:212-227` (prod-валидатор SECRET_KEY), `.env.prod.example:22` (`RUN_MIGRATIONS_ON_STARTUP=false`) | Слабый `SECRET_KEY` в проде → форж JWT/HMAC; авто-миграции в проде → гонка реплик | Чек-лист деплоя: сильный `SECRET_KEY` (≥32, не из `_WEAK_SECRET_KEYS`), `RUN_MIGRATIONS_ON_STARTUP=false`. Код уже fail-fast'ит на слабом ключе в prod | S | VERIFIED · resolved (код валидирует) |

---

## Фаза 1 — Операционная устойчивость

> Бэкапы, миграции вне lifespan, CI, тесты — **уже сделаны** (см. «Что уже сделано»). Здесь — то, что в этой категории ещё открыто.

| # | Что | Где (`file:line`) | Риск | Фикс | Оценка | Зав. | Статус |
|---|---|---|---|---|---|---|---|
| **OBS-1** | В прод-compose нет Prometheus/Grafana/Flower | `docker-compose.prod.yml` (сервисов нет); инструментация есть: `main.py:145-148` (`Instrumentator`, гейт `METRICS_ENABLED`), `monitoring/prometheus.yml` таргетит `backend:8000` | В проде `/metrics` никто не скрейпит → нет ретенции метрик, дашбордов, видимости Celery | Решить: добавить prometheus+grafana(+flower за auth) в прод-compose ИЛИ внешний managed-Prometheus. Гейты `METRICS_ENABLED`/`SENTRY_DSN` оставить | M | — | VERIFIED · partial |
| **2.6** | Celery result/broker на Redis без AOF; нет startup-реконсиляции «зависших» уроков | `celery_app.py:55-58` (broker=backend=Redis), `docker-compose.prod.yml` redis без `--appendonly` | Рестарт/flush Redis → `AsyncResult` отдаёт PENDING для готовой задачи; урок может зависнуть в non-terminal статусе | Включить AOF (`redis-server … --appendonly yes`) на прод-инстансе И/ИЛИ startup-джоб, переводящий уроки в non-terminal статусе с мёртвым `task_id` → `error`. Result-backend НЕ переносить в БД | M | — | VERIFIED · open (mitigated через `lesson.status`) |
| **2.8** | Дисковый `summaries_cache/` растёт без TTL/eviction | `services/vision_analysis.py:284,349-368` (пишет `<hash>.txt`, без чистки); для сравнения slides-кэш ограничен `TTLCache` (`video_service.py:149-152`) | На local-storage деплое каталог тихо забивает диск | Добавить TTL-проход в существующий beat-джоб `purge_soft_deleted` (удалять `.txt` старше N дней). **Второй beat НЕ заводить** | M | — | VERIFIED · partial |
| **2.7** | `vision_pipeline` чистит `work_dir` даже при падении (video — нет) | `tasks/vision_pipeline.py:255-256` (безусловный `rmtree`) vs `tasks/video_pipeline.py:679-683` (retain при `_success=False`) | Падение vision-анализа не оставляет артефактов для разбора | Зеркалить video: `rmtree` только при `_success`, иначе `logger.warning("work_dir_retained")`. `_success` уже в scope того же `finally` (`vision_pipeline.py:251`) | S | — | VERIFIED · partial |
| **2.3** | `video_url` хранит резолвнутый/host-prefixed URL (асимметрия с относительным `pptx_path`) | `models/lesson.py:82-83`; пишется `tasks/video_pipeline.py:616` (`get_url(...)`); читается через `resign_url` `routers/lessons.py:62,69` | TTL-протухание митигировано (`resign_url` переподписывает на чтении, `storage_service.py:201-217`), НО при смене backend local↔s3 / формы URL парсер `resign_url` тихо возвращает старый URL | Хранить относительный ключ в `video_url` (как `pptx_path`), резолвить в сериализаторе через `get_url`. Убирает хрупкий парсинг в `resign_url` | M | — | VERIFIED · open (риск сужен) |
| **5.2** | Healthcheck'и редки в dev-compose | `docker-compose.yml:12` (только postgres); backend `depends_on` redis/silero `condition: service_started` (`:87,89`). Прод — полный набор (`docker-compose.prod.yml:45-50` anchor) | Только dev-DX: backend может стартовать раньше готовности зависимостей (флапающий локальный старт). Прод ОК | Dev-only: redis healthcheck + переиспользовать прод-anchor `&celery-healthcheck`, backend `depends_on … service_healthy` | M | — | VERIFIED · partial |
| **5.3-off** | Бэкап только на том же хосте (нет off-host копии) | `docker-compose.prod.yml:84-119` (`db_backup` → volume `db_backups`), комментарий `:82-83` | Потеря хоста/диска уносит и БД, и бэкапы — нет DR | Post-MVP: синк `/backups` в S3/Object Storage (креды уже есть — `STORAGE_BACKEND=s3` / `storage_service`) | M | — | VERIFIED · resolved (single-instance), off-host open |

---

## Фаза 2 — Готовность к нагрузке

> S3-бэкенд **уже реализован** (см. «Что уже сделано» — доклад устарел). Здесь — остаток масштабирования.

| # | Что | Где (`file:line`) | Риск | Фикс | Оценка | Статус |
|---|---|---|---|---|---|---|
| **3.3-buf** | S3 `save_upload_bounded` буферит загрузку в память до cap (нет multipart-стриминга) | `services/storage_service.py:64-102` (S3Backend, `upload_fileobj`), буфер `:149-151,157,182` | Крупные загрузки (видео до 2 ГБ) на S3-бэкенде едят память воркера | Перейти на multipart-upload (`create_multipart_upload`/`upload_part`) для стриминга вместо буфера | M | VERIFIED · partial |
| **Ollama** | Узкое место LLM/vision при росте (один инстанс Ollama; `celery_quiz` c=2 × `QUIZ_GRADING_WORKERS=4`) | `docker-compose.yml` `celery_quiz`/`celery_vision`, `constants.py:162` `QUIZ_GRADING_WORKERS` (см. KNOWN_PROBLEMS §6.6) | Пиковая нагрузка (много открытых ответов/генераций) упрётся в один Ollama → таймауты/`needs_review` | Дефолт уже Polza-облако (`.env.example`); при росте — `--pool=gevent` или снизить `QUIZ_GRADING_WORKERS`, либо вынести инференс (vLLM/Yandex). Решать по фактическим жалобам | M | VERIFIED (config) · open |
| **3.6** | `VISION_SUMMARY_CONCURRENCY` — хардкод-константа, не env | `constants.py:149` (`=4`), `vision_analysis.py:308` (`Semaphore`); в `config.py` ключа нет | Нельзя подстроить под слабый/мощный хост без пересборки образа | Вынести в `config.py` Settings (env, default 4), `constants.py` читает из настроек — как `TTS_WORKERS`/`SLIDES_CACHE_*` | S | VERIFIED · partial |
| **3.8** | PPTX-загрузка не пре-рендерит слайды | `routers/uploads.py:194-220` (`upload_pptx` только сохраняет); рендер ленив в `video_service.py:182` (~20-30 с/хит) | Первая генерация платит полную стоимость LibreOffice→PDF→PNG инлайн | Опционально: best-effort пре-рендер Celery-таской в очередь `video` с **тем же** content-hash ключом кэша, чтобы пайплайн получил cache-hit. Ответ загрузки не блокировать | M | VERIFIED · open |
| **3.5** | LibreOffice спавнится на каждый джоб (нет демона) | `video_service.py:239` (`libreoffice --headless`), `:260` (`pdftoppm`) | Холодный старт LO доминирует в латентности первого рендера; параллельные генерации жмут память на `video` (c=2) | Приемлемый тех-долг сейчас. При боттлнеке — `unoserver`/persistent `soffice` сайдкаром через UNO; поведение кэш-ключа не менять | L | VERIFIED · open |

---

## Фаза 3 — Продуктовые дыры и тех-долг

| # | Что | Где (`file:line`) | Риск | Фикс | Оценка | Зав. | Статус |
|---|---|---|---|---|---|---|---|
| **3.2** | N+1 на студенческом hot-path (guard владельца уже починен) | `routers/students.py:187,190,200` (`get_lesson_for_student`) и `:211,214` (`_get_progress`) — 3 последовательных round-trip; ср. `dependencies.py:215-231` (один JOIN) | Каждый просмотр урока/прогресса студента = 3 запроса; под нагрузкой множит латентность | Грузить Lesson с `joinedload(Lesson.module).joinedload(Module.course)` одним запросом (зеркало `get_owned_lesson`); вынести enrollment+visibility в общий async-dep | M | 6.4 | VERIFIED · partial |
| **6.4** | Дублированная логика доступа к уроку в `students.py` (не на `require_lesson_access`) | `routers/students.py:191-197,215-221` (inline enrollment-проверка) vs `dependencies.py:173` (унифицированный guard, используют `comments.py:30,52`, `assignment_student.py:57`) | Правила enrollment/visibility разъезжаются — правка в `require_lesson_access` молча минует эти 2 пути (утечка/несовпадение 403/404) | Переключить `get_lesson_for_student`/`_get_progress` на `Depends(require_lesson_access)`; async-паттерн сохранить | M | — | VERIFIED · open |
| **6.3-ui** | Мёртвая quiz-ветка в `LessonPlayer` (сам квиз реализован) | `components/LessonPlayer.vue:40-45` (заглушка «Отметьте урок пройденным…»); реальный квиз — `QuizTaker.vue`, подключён `pages/student/courses/[courseId]/lessons/[lessonId].vue:226-230`, бэкенд `routers/quiz_student.py` | Путающий мёртвый текст; KNOWN_PROBLEMS §6.3 ложно числит фичу нереализованной | Удалить ветку `LessonPlayer.vue:40-45`; пометить KNOWN_PROBLEMS §6.3 resolved | S | — | VERIFIED · resolved (фича) + dead-code |
| **6.1** | Неиспользуемая зависимость `pdf2image` (модуль `slide_renderer` удалён) | `requirements.txt:22` (`pdf2image`, ноль импортов в `backend/`); `backend/app/utils/slide_renderer.py` — отсутствует | Раздувает образ; стале-ссылки в KNOWN_PROBLEMS §6.1 / DECISIONS §11 на несуществующий файл | Удалить строку `pdf2image` из `requirements.txt`; обновить KNOWN_PROBLEMS §6.1 / DECISIONS §11 (рендер инлайн в `video_service.py`) | S | — | VERIFIED · partial (dead dep) |
| **6.9** | Нет GC устаревших версий `quiz_questions` | `quiz_service.py:163-167,234` (ставит `superseded_at`, без DELETE); `tasks/purge_pipeline.py` (`purge_soft_deleted`, `:270`) QuizQuestion не трогает | Каждое редактирование/regenerate теста копит строки навечно | Расширить `purge_soft_deleted` GC-проходом: удалять `QuizQuestion` со старым `superseded_at`, **только** если ни один live-снимок попытки не ссылается на `(id, version)`. Без второго beat | M | 6.10 | VERIFIED · open (тех-долг) |
| **6.10** | Нет миграции legacy full-snapshot попыток на pointer-формат | `grading_service.py:281` (`snapshot_pointers` → `[]` если нет `pointers`), `quiz_service.py:290-291` (`resolve_snapshot` → `[]`) — fallback на полный payload отсутствует | Если в проде есть попытки в дореформенном формате — они отрезолвятся в 0 вопросов | Проверить в БД, есть ли такие строки. Если да — one-off миграция или толерантная ветка в `resolve_snapshot`. Если нет — задокументировать «pointer-only», закрыть won't-fix | M | — | code-claim VERIFIED · existence **UNVERIFIED** (нужна инспекция БД) |
| **1.8-res** | Cap декомпрессии `.docx` — best-effort (читает `file_size` из центрального каталога zip) | `routers/uploads.py:64-69`; `constants.py:28` (`MAX_DECOMPRESSED_DOCX_BYTES=100MB`) | Крафтнутый zip может занизить заявленный размер; cap не строгая гарантия (XXE отдельно закрыт `resolve_entities=False`) | Низкий приоритет: при необходимости — стримить распаковку с реальным счётчиком байт вместо доверия метаданным | S | — | VERIFIED · partial |

---

## Документация vs код (разрешённые противоречия)

| # | Противоречие | Вердикт по коду | Действие в доках |
|---|---|---|---|
| 1 | KNOWN_PROBLEMS §3.1 (баннер «решено») vs «Карта приоритетов» в конце файла (всё ещё числит 3.1 и часть 1.x как фиксы) | **Код прав: решено.** 4 воркера + ровно 1 beat (`docker-compose.yml:102,131,160,164,194`; `celery_app.py:77-82`); каждый продюсер роутит в живую очередь (`slides.py:154`, `lessons.py:358`, `quiz_student.py:539`, `email_pipeline.py:26`) | Убрать устаревшие записи из «Карты приоритетов» (`KNOWN_PROBLEMS.md:~556`) |
| 2 | ARCHITECTURE §9–10 (S3/Sentry/Prometheus присутствуют) vs DEPLOYMENT §7 / KNOWN_PROBLEMS 3.3 («не реализовано») | **Обе стороны частично правы.** S3-бэкенд реализован (`storage_service.py:64-102`, sync boto3) — DEPLOYMENT/KNOWN_PROBLEMS 3.3 **устарели**. Sentry+Prometheus инструментация есть и гейтится (`main.py:56-82,145-148`; `celery_app.py:27-49`) — ARCHITECTURE прав. НО прод-compose **не разворачивает** Prometheus/Grafana/Flower, а `SENTRY_DSN` пуст в шаблоне — DEPLOYMENT §7 прав для прод-рантайма | KNOWN_PROBLEMS 3.3 / DEPLOYMENT §7 → пометить S3 реализованным (sync boto3 + `STORAGE_BACKEND`, не aiobotocore/`STORAGE_PROVIDER`); развести «реализовано в коде» vs «не развёрнуто в прод-compose» для observability (см. OBS-1) |
| 3 | README-нота: «CLAUDE.md описывает старую Bearer/localStorage `useApi`» | **Код прав: cookie + double-submit CSRF.** `useApi.ts` — `credentials:'include'`, `X-CSRF-Token`, singleflight refresh; ноль вхождений `Bearer`/`localStorage`/`Authorization` в `useApi.ts`+`stores/auth.ts` | Уже синхронизировано в этой сессии (CLAUDE.md и README обновлены); нота снята |
| 4a | KNOWN_PROBLEMS §1.4 (`/files/*` без auth, `app.mount StaticFiles`) | **Код: HMAC-подписанные URL, `StaticFiles` нет.** `main.py:293-298`, `files.py:48-60`, `signed_url_service.py`. Остаток — bearer-style в пределах TTL (см. P0-2) | §1.4 → partial: переписать на HMAC-router; ссылку на `main.py:161 app.mount` убрать |
| 4b | KNOWN_PROBLEMS §1.5 (дефолт `SECRET_KEY`) | **Код опровергает.** `config.py:38` — поле без дефолта + prod-валидатор `:212-227` (`_WEAK_SECRET_KEYS`, ≥32) | §1.5 → resolved |
| 4c | KNOWN_PROBLEMS §1.8 (XXE/XML-bomb в `.docx`) | **Закрыто.** Cap до парсинга `uploads.py:64-69`; `resolve_entities=False` в python-docx 1.1.2. Остаток — §1.8-res | §1.8 → resolved (с заметкой про best-effort cap) |
| 4d | KNOWN_PROBLEMS §1.9 (CORS) | **Закрыто.** `main.py:220-241`: warn в dev, `RuntimeError` в prod, credentials off при `*` | §1.9 → resolved |
| 5 | KNOWN_PROBLEMS §4.5 («ruff — заглушка/no-op») + комментарий в `ci.yml` | **Код прав: ruff настроен и enforced.** `pyproject.toml:1,9-10`; `ci.yml:47-48` (`ruff check`/`format`), `lint.yml:24-27` | §4.5 → resolved; поправить устаревший комментарий `ci.yml:15-17`; `lint.yml` (только `main`) избыточен относительно `ci.yml` (master+main) — кандидат на удаление |
| 6 | KNOWN_PROBLEMS §6.1 / DECISIONS §11 ссылаются на `utils/slide_renderer.py` | **Файл удалён** (CLAUDE.md прав). Но `pdf2image` висит в `requirements.txt:22` без импортов | §6.1/§11 → пометить модуль удалённым; убрать dead dep (см. 6.1) |
| 7 | KNOWN_PROBLEMS §6.3 («квиз в плеере не реализован») | **Реализован.** `QuizTaker.vue` подключён (`…/[lessonId].vue:226-230`), `quiz_student.py` эндпоинты есть; мёртвая ветка `LessonPlayer.vue:40-45` | §6.3 → resolved (см. 6.3-ui) |
| 8 | KNOWN_PROBLEMS 2.1/2.2 (нет UNIQUE на `access_code` / `LessonProgress`) | **Опровергнуто.** `course.py:38` `unique=True` + миграция `4995eaa3d3aa`; `enrollment.py:53-55` `UniqueConstraint` + миграция `e4dd7b2e16d3` + recovery в `progress_service.py:38-41` | 2.1/2.2 → resolved |

---

## Что уже сделано (подтверждённо закрыто — в планах не висит)

| Пункт | Доказательство (`file:line`) |
|---|---|
| Auth-оверхол: httpOnly-куки + CSRF, Argon2id, ротация refresh-семейств, blacklist, rate-limit (1.1/1.2/1.3/1.6/1.7) | `useApi.ts` (cookie+CSRF, нет Bearer/localStorage); `dependencies.py`, `auth_service.py`; см. AUTH_FLOW.md |
| `SECRET_KEY` без дефолта + prod-валидатор (1.5) | `config.py:38,212-227` |
| `.docx` XXE/zip-bomb закрыт (1.8) | `uploads.py:64-72`, `constants.py:28`, python-docx `resolve_entities=False` |
| CORS: warn в dev, fatal в prod (1.9) | `main.py:220-255` |
| `/files/*` через HMAC-подписанные URL, без `StaticFiles` (1.4 — частично) | `main.py:293-298`, `signed_url_service.py`, `files.py:48-60` |
| Разделение Celery-очередей + ровно один beat (3.1) | `docker-compose.yml:102,131,160,164,194`; `celery_app.py:77-82` |
| Миграции вне lifespan в проде (5.1) | `config.py:184`, `main.py:116-126`, `docker-compose.prod.yml:173-185`, `.env.prod.example:22` |
| Backup БД сайдкаром (5.3, single-instance) | `docker-compose.prod.yml:84-119` |
| Тесты: unit + integration + conftest/factories (4.1) | `backend/tests/unit/*`, `backend/tests/integration/*`, `backend/pyproject.toml:27,33-37` |
| Ruff настроен + enforced в CI, coverage-gate 70% (4.5) | `pyproject.toml:1,9-10`, `ci.yml:47-48,84-88`, `lint.yml:24-27` |
| S3-бэкенд хранилища реализован (3.3) | `storage_service.py:64-102`, `config.py:143,155-160` |
| UNIQUE `access_code` (2.1) | `course.py:38`, миграция `4995eaa3d3aa` |
| UNIQUE `LessonProgress(enrollment,lesson)` + race-recovery (2.2) | `enrollment.py:53-55`, миграция `e4dd7b2e16d3`, `progress_service.py:38-41` |
| N+1 в guard владельца устранён (один JOIN) (3.2 — частично) | `dependencies.py:215-231` |
| Пулы пайплайна вынесены в `constants.py`, стриминг `as_completed` цел (3.7/4.4) | `video_pipeline.py:79-82,552-557,565,581`, `constants.py:132-133` |
| `courses/index.vue` — реальная страница, не заглушка (6.2) | `pages/courses/index.vue:16,94-100` |
| Квиз-плеер реализован (6.3) | `QuizTaker.vue`, `quiz_student.py`, `…/[lessonId].vue:226-230` |
| `utils/slide_renderer.py` удалён (6.1 — частично) | файл отсутствует; рендер в `video_service.py:239,260` |

---

## Кандидаты — требуют решения продукта/архитектуры

> Не выдуманные фичи: всё ниже следует из кода/докладов, но выбор зависит от продуктовых/нагрузочных приоритетов.

- **Жёсткость доступа к `/files/*`** (P0-2): принять bearer-TTL для MVP, или сократить TTL / привязать к сессии для приватного/платного контента. Tradeoff приватность ↔ возможность `<img src>`-загрузки без JWT.
- **Прод-observability** (OBS-1): развернуть Prometheus/Grafana/Flower в прод-compose vs внешний managed-Prometheus vs оставить только Sentry. Зависит от того, нужны ли дашборды/ретенция метрик на запуске.
- **Масштабирование инференса** (Ollama/§6.6): остаться на облаке (Polza, дефолт) vs поднять vLLM/Yandex vs тюнить `QUIZ_GRADING_WORKERS`/`--pool`. Решать по фактической нагрузке, не превентивно.
- **Пре-рендер слайдов** (3.8): тратить вычисления на загрузке (быстрее «Создать видео») vs ленивый рендер (дешевле, если PPTX часто не доходит до генерации).
- **LibreOffice-демон** (3.5): инвестировать в `unoserver`-сайдкар только если холодный старт LO станет реальным боттлнеком.
- **Legacy quiz-снимки** (6.10): нужна инспекция прод-БД — есть ли попытки в дореформенном full-snapshot формате. Без этого статус по затронутым строкам — **UNVERIFIED**.

---

## Связанные документы

- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — исходный индекс кандидатов (часть записей помечена этим аудитом как устаревшая — см. «Документация vs код»).
- [DECISIONS.md](DECISIONS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DEPLOYMENT.md](DEPLOYMENT.md) — контекст решений и прод-рантайма.
