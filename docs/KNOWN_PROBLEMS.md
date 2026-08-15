# KNOWN_PROBLEMS — технический долг и слабые места

> Все известные проблемы проекта в одном месте, с предлагаемыми фиксами. Сгруппировано по категориям; внутри — по убыванию приоритета.
>
> Каждая запись содержит:
> - **Где** — файл/строка, где живёт проблема
> - **Что не так** — симптом или потенциальный сбой
> - **Почему опасно**
> - **Фикс** — конкретный шаг, который её решает
>
> Решённые пункты из этого документа удалены; остаются только открытые. Нумерация
> сохраняет исторические номера (на них ссылаются другие доки), поэтому в ней есть пропуски.

---

## Содержание

1. [Security](#1-security)
2. [Correctness и race conditions](#2-correctness-и-race-conditions)
3. [Performance и масштабирование](#3-performance-и-масштабирование)
4. [Maintainability и developer experience](#4-maintainability-и-developer-experience)
5. [Operational риски](#5-operational-риски)
6. [Мёртвый код и дубли](#6-мёртвый-код-и-дубли)

---

## 1. Security

### 1.4 ⚠ `/files/*` отдаётся без авторизации — accepted-with-mitigation (MVP)

- **Где:** `services/signed_url_service.py`, `routers/files.py`.
- **Что не так (residual):** подписи bearer-style — uid/sig в URL, без session-binding. Утёкшая ссылка валидна у любого до истечения TTL.
- **Митигация (2026-06):** TTL сокращён с 3600 до 1800 с для видео, 600 с для слайдов. Фронтенд прозрачно перезапрашивает свежий URL при 403. HMAC-алгоритм и nginx `auth_request`-контракт не тронуты. Подробнее: [DECISIONS.md §38](DECISIONS.md#38-сокращение-ttl-подписанных-url--403-resilience-плеера-known_problems-14-partial).
- **Остаточный риск:** окно эксплуатации — 30 мин для видео. Принято для MVP.
- **Будущий путь:** per-request signed URLs (mint at API-request time) — правильное решение для платного контента. Session-binding отклонён (убивает CDN-кеш). Переход на S3 даёт presigned URLs из коробки.

### 1.9 CORS `allow_credentials` принудительно `False` при `*`

- **Где:** [backend/app/main.py:88](../backend/app/main.py).
- **Что не так:** условие `allow_credentials=False if _allow_all else True`. Если кто-то поставит `CORS_ORIGINS=["*"]` для удобства, credentials отключатся (что корректно по CORS-спеке), но это может неожиданно сломать клиента, ожидающего credentials.
- **Фикс:** не критично; стоит просто залогировать предупреждение при `_allow_all`, чтобы было видно в логах.

---

## 2. Correctness и race conditions

### 2.3 `pptx_path` vs `video_url` — разная семантика

- **Где:** [backend/app/models/lesson.py](../backend/app/models/lesson.py).
- **Что не так:** `pptx_path` хранит относительный путь (`pptx/<uuid>_file.pptx`), а `video_url` хранит полный URL (`http://localhost:8000/files/videos/<uuid>.mp4`).
- **Почему опасно:** при смене `BASE_URL` (например, переезд на новый домен) старые `video_url` остаются битыми. Любой новый эндпоинт, возвращающий `lesson.video_url`, должен помнить об этой несимметрии.
- **Фикс:** хранить относительный путь и в `video_url`, конвертировать через `storage_service.get_url(...)` в момент сериализации (в Pydantic `@field_validator` или в роутере).

### 2.4 Гонка при `re-analyze` урока

- **Где:** [backend/app/tasks/vision_pipeline.py:analyze_presentation_task](../backend/app/tasks/vision_pipeline.py).
- **Что не так:** старые `SlideText` удаляются в начале задачи (`session.query(SlideText).filter(...).delete()`). Если пользователь во время анализа открыл редактор слайдов в другой вкладке и сохраняет правки — `PATCH /slides/{slide_id}` пройдёт на удалённой записи (уже не существует) → 404.
- **Фикс:** установить `lesson.status = analyzing` (это уже делается) И во фронте дополнительно блокировать редактор пока статус не `ready_for_edit`. Уже частично сделано через middleware-флоу, но если открыты две вкладки — может стрельнуть.

### 2.5 LLM возвращает не N чанков → fallback ухудшает качество

- **Где:** [backend/app/services/llm_service.py:split_and_annotate_ssml](../backend/app/services/llm_service.py).
- **Что не так:** если LLM вернёт `chunks` длины ≠ `slides_count` или невалидный JSON — вызывается `_fallback_ssml`, который делит текст по предложениям без учёта семантики.
- **Почему опасно:** в логах warning, пользователь не видит. Видео формально создаётся, но текст на слайдах часто не соответствует тому, что показано.
- **Фикс:** retry один раз с более жёстким промптом («previous response had N chunks but expected M»). Если повторно неудача — сохранить ошибку в `lesson.status = error` вместо тихого fallback.

### 2.6 Прогресс задачи пропадает при перезапуске Redis — mitigated

- **Где:** [backend/app/celery_app.py](../backend/app/celery_app.py) — `backend=settings.REDIS_URL`.
- **Что не так (residual):** Celery result backend = Redis. После перезапуска Redis (или `flushdb`) `AsyncResult(task_id).status` возвращает `PENDING` для завершённых задач — прогресс-мета теряется.
- **Митигации (2026-06):** источник истины для фронта — **`lesson.status` в БД** (см. `test_task_status_db_authoritative.py`); при старте backend `_reconcile_stuck_lessons` ([main.py](../backend/app/main.py)) помечает `error` уроки, зависшие в `analyzing`/`processing` дольше `STUCK_LESSON_GRACE_MINUTES` (120 мин); синтезированные слайды чекпоинтятся в Redis и переиспользуются при повторном запуске.
- **Остаточный риск:** между рестартом Redis и реконсиляцией (до 2 ч) фронт видит «PENDING» у живого на вид таска. Принято.

### 2.7 `rmtree(work_dir)` при падении — остался только в vision_pipeline

- **Где:** [tasks/vision_pipeline.py:254-255](../backend/app/tasks/vision_pipeline.py) — безусловный `rmtree` в `finally`.
- **Что не так:** `video_pipeline` уже чинён (при ошибке `work_dir` сохраняется, `work_dir_retained` в логах), а vision-анализ по-прежнему стирает артефакты падения.
- **Фикс:** зеркалить video: `rmtree` только при `_success`, иначе warning. `_success` уже в scope этого `finally`.

### 2.9 Журнал оценок: pre-grade не поддерживается

- **Где:** [backend/app/routers/gradebook.py](../backend/app/routers/gradebook.py), [frontend/src/pages/courses/[id]/gradebook.vue](../frontend/src/pages/courses/[id]/gradebook.vue).
- **Что не так:** PATCH `/courses/{id}/progress/{progress_id}` работает только по уже существующей записи `lesson_progress`. Если студент ещё не открывал/не проходил урок, `progress_id == null` — преподаватель не может выставить балл «авансом»: ячейка нередактируема, эндпоинт даст 404 на чужой/несуществующий `progress_id`. Это сознательное продуктовое ограничение, чтобы не плодить пустые записи прогресса и не размывать семантику `is_completed`/`completed_at`.
- **Почему это ОК сейчас:** учитель оценивает реальное прохождение, а не «авансом»; UI явно сообщает через прочерк «—» и tooltip, что студент не проходил урок.
- **Фикс (если потребуется):** добавить отдельный POST `/courses/{id}/lessons/{lesson_id}/progress` для idempotent upsert записи прогресса с пустым `quiz_score` + ручным баллом; UI заменит нередактируемый прочерк на «Выставить балл» по таким ячейкам.

---

## 3. Performance и масштабирование

### 3.2 N+1 в `_get_owned_lesson` и `_get_owned_course`

- **Где:** [backend/app/routers/lessons.py:26-34](../backend/app/routers/lessons.py), [routers/slides.py:31-39](../backend/app/routers/slides.py), [routers/courses.py:25-31](../backend/app/routers/courses.py).
- **Что не так:** три последовательных `db.get` (lesson → module → course) на каждом эндпоинте. Это 3 round-trip к БД для одной только проверки прав.
- **Фикс:** один JOIN:
  ```python
  result = await db.execute(
      select(Lesson, Course)
      .join(Module, Module.id == Lesson.module_id)
      .join(Course, Course.id == Module.course_id)
      .where(Lesson.id == lesson_id)
  )
  row = result.one_or_none()
  if not row: raise 404
  lesson, course = row
  if course.owner_id != user.id: raise 403
  ```

### 3.3 Локальное file storage не масштабируется

- **Где:** [backend/app/services/storage_service.py](../backend/app/services/storage_service.py).
- **Что не так:** при горизонтальном масштабировании backend (две реплики за load balancer) реплики не видят файлов друг друга.
- **Фикс:** добавить S3-бекенд в `storage_service`. Интерфейс уже абстрактный (`save_upload`, `get_url`, `get_full_path`, `delete_file`), нужно реализовать второй вариант через `aiobotocore` или `aioboto3`. Селектор провайдера через env-переменную `STORAGE_PROVIDER=local|s3`.

### 3.5 LibreOffice тяжёлый и единственный

- **Где:** [backend/app/services/video_service.py:convert_pptx_to_images](../backend/app/services/video_service.py).
- **Что не так:** LibreOffice — это толстое C++-приложение, медленный старт (~5 сек на каждый запуск), нестабилен на сложных PPTX. Зависимость от его профиля (`_lo_profile/`) добавляет ещё накладных расходов.
- **Фикс — не быстрый, но идейно:**
  - Запускать LibreOffice как отдельный демон-сервис (libreoffice headless `--accept`) и общаться через UNO API.
  - Или вынести в отдельный микросервис `pptx-renderer` (отдельный контейнер, REST API).

### 3.8 Pre-render слайдов не делается на этапе загрузки PPTX

- **Где:** [backend/app/routers/uploads.py:upload_pptx](../backend/app/routers/uploads.py).
- **Что не так:** при загрузке PPTX происходит **только** сохранение файла. PNG слайдов не генерятся, кеш не заполняется. Это значит — при первой генерации видео пользователь ждёт ~30 секунд только на PPTX→PNG.
- **Фикс:** отдельная Celery-задача `pre_render_slides.delay(lesson_id)` сразу после загрузки. К моменту, когда пользователь нажмёт «Создать видео», PNG уже в кеше.

---

## 4. Maintainability и developer experience

### 4.2 ⚠ `pages/lessons/[id]/index.vue` — ~820 строк

- **Где:** [frontend/src/pages/lessons/[id]/index.vue](../frontend/src/pages/lessons/[id]/index.vue).
- **Что не так:** часть секций уже вынесена в `components/lesson/*` (PptxUploader, ScriptPanel, VideoGenerationPanel, VisionPanel, WorkflowNav), но сама страница продолжает расти и держит всю оркестрацию:
  - выбор режима;
  - загрузку PPTX;
  - manual: редактор скрипта + загрузку файла со скриптом;
  - auto: запуск vision-анализа + polling;
  - generate-video flow + polling;
  - резюме polling после refresh;
  - отображение MP4.
  Всё реактивное состояние и таймеры — в одном setup'е.
- **Фикс:** декомпозировать на компоненты по фазам:
  - `<LessonPptxUpload>` — секция 2.
  - `<LessonScriptInput>` — секция 3a.
  - `<LessonVisionAnalysis>` — секция 3b с поллингом.
  - `<LessonGenerateVideo>` — секция 4 с поллингом.
  - `<LessonVideoPlayer>` — секция 5.

### 4.3 Дублирование `_get_owned_lesson` / `_get_owned_course`

- **Где:** [routers/lessons.py:26](../backend/app/routers/lessons.py), [routers/slides.py:31](../backend/app/routers/slides.py).
- **Что не так:** один и тот же helper скопирован в два роутера.
- **Фикс:** вынести в общий модуль `app/dependencies.py` или `app/auth_dependencies.py`. Сделать FastAPI-зависимостями (`Depends`):
  ```python
  async def get_owned_lesson(
      lesson_id: UUID,
      user: User = Depends(require_teacher),
      db: AsyncSession = Depends(get_db),
  ) -> Lesson:
      ...
  ```

### 4.5 Нет eslint/prettier для frontend

- **Где:** репозиторий (frontend).
- **Что не так:** backend линтуется `ruff` (правила E/F/I), а для frontend нет `eslint`/`prettier` — стиль и потенциальные баги в `.vue`/`.ts` не проверяются автоматически.
- **Фикс:** `eslint` + `prettier` (vue-eslint-parser) и отдельный lint-job для frontend в CI.

### 4.6 Нет CHANGELOG.md · ~~нет CONTRIBUTING.md~~ (частично закрыто)

- **Где:** корень.
- **Что не так:** ~~нет единого описания, как добавлять новые эндпоинты, новые миграции, новые Celery-задачи~~. Нет changelog.
- **Фикс:** ✅ `CONTRIBUTING.md` создан (описывает добавление роутов/моделей/Celery-задач, запрет npm, команды через docker-compose); заодно добавлены `LICENSE`, `SECURITY.md`, `THIRD_PARTY_LICENSES.md`. Осталось: завести `CHANGELOG.md`.

### 4.7 `StatusBadge` хардкодит список статусов

- **Где:** [frontend/src/components/StatusBadge.vue](../frontend/src/components/StatusBadge.vue).
- **Что не так:** компонент знает только перечисленные значения. Добавишь новый статус в `LessonStatus` enum в Python — компонент покажет «unknown».
- **Фикс:** вместо хардкода — мапа статусов в `composables/useStatuses.ts`, единый источник истины. Обновлять при изменении enum.

### 4.8 `test_students_routes.py`: тест не проверяет изоляцию курсов

- **Где:** `backend/tests/integration/test_students_routes.py`, тест вокруг строки 106-108.
- **Что не так:** тест создаёт `_other` — курс того же teacher, в который student НЕ записан, — но нигде не проверяет, что `_other` отсутствует в ответе API для student'а. При lint-фиксе (2026-08-14) переменная переименована в `_other`, чтобы убрать F841, без добавления недостающего assert.
- **Почему не критично:** enrollment-фильтрация покрыта в других тестах; здесь конкретно не хватает assert на изоляцию именно в этом сценарии.
- **Фикс по запросу:** добавить проверку, что `_other.id` отсутствует среди курсов, вернувшихся student'у в этом эндпоинте.

---

## 5. Operational риски

### 5.1 Миграции: race при горизонтальном масштабировании

- **Где:** [backend/app/main.py:_ensure_schema_at_head](../backend/app/main.py), [docker-compose.prod.yml](../docker-compose.prod.yml) (сервис `migrate`).
- **Что не так:** авто-`upgrade head` спрятан за `RUN_MIGRATIONS_ON_STARTUP` (dev), а прод гоняет миграцию one-shot сервисом `migrate` до роллаута — базовый кейс закрыт. Открытым остаётся горизонтальное масштабирование: несколько реплик backend, стартующих параллельно, могут одновременно инициировать миграцию (Alembic берёт advisory lock, но это снижает риск, а не устраняет его).
- **Фикс:** держать миграцию строго отдельным pre-deploy шагом (в проде уже так); при multi-replica не полагаться на lifespan.

### 5.1a ⚠ `.gitignore` игнорирует все миграции — новая ревизия не попадёт в коммит

- **Где:** [.gitignore](../.gitignore) строка 40 (`backend/alembic/versions/*`), [backend/alembic/versions/](../backend/alembic/versions/). Единственная миграция репозитория `c2f900c2bf7a_init_schema.py` видна только благодаря персональному исключению ниже по файлу (`!backend/alembic/versions/c2f900c2bf7a_init_schema.py`) — на любое другое имя оно не распространяется.
- **Что не так:** файл, сгенерированный `alembic revision --autogenerate`, не появляется в `git status` — он отфильтрован как игнорируемый. Изменил модель, сгенерировал ревизию, закоммитил «всё» — ревизия осталась только на машине разработчика.
- **Почему опасно:** прод гоняет `alembic upgrade head` (в dev — из lifespan `main.py:_ensure_schema_at_head`, в prod — one-shot сервисом `migrate`), и без пропавшей ревизии он молча поднимается на старой схеме: код ждёт новую колонку, БД её не имеет. Ошибка всплывает не на деплое, а на первом запросе, который эту колонку трогает. Симметричный риск — потерянная ревизия в середине цепочки: `down_revision` следующей миграции указывает в никуда.
- **Фикс:** до починки — добавлять каждую новую ревизию явно (`git add -f backend/alembic/versions/<file>.py`) и проверять `git status --ignored backend/alembic/versions/` перед коммитом. По-хорошему — снять строку игнора (миграции обязаны быть в VCS) либо сузить её до реально временных файлов; правка `.gitignore` сознательно вынесена за рамки задачи, где это было обнаружено.

### 5.2 Нет healthcheck воркеров в dev-compose (в prod — есть)

- **Где:** [docker-compose.yml](../docker-compose.yml) vs [docker-compose.prod.yml](../docker-compose.prod.yml).
- **Что не так:** prod-compose проверяет каждый воркер общим anchor'ом (`celery inspect ping`), но в dev-compose healthcheck только у `postgres` — упавший воркер выглядит «running».
- **Фикс:** скопировать anchor из prod-compose в dev, если тихие падения воркеров начнут мешать разработке. Низкий приоритет.

### 5.3 Бэкап БД только на том же хосте

- **Где:** инфра, [docker-compose.prod.yml](../docker-compose.prod.yml) (сайдкар `db_backup`).
- **Что не так:** `db_backup` делает `pg_dump -Fc` в volume `db_backups` (ретенция `BACKUP_RETENTION_DAYS`) — это спасает от `docker volume rm`/повреждения данных, но не от потери самого хоста: off-site копии нет.
- **Фикс:** выгружать дампы в Object Storage / внешнее хранилище (post-MVP).

### 5.4 `host.docker.internal` на Linux: закрыто для backend, не для воркеров

- **Где:** [docker-compose.yml](../docker-compose.yml).
- **Что не так (residual):** `extra_hosts: host.docker.internal:host-gateway` прописан **только сервису `backend`**. Celery-воркеры (`celery_vision` ходит в vision-LLM, `celery_video`/`celery_quiz` — в текстовый) на Linux-хосте с **локальным Ollama** получат ConnectionRefused.
- **Почему не критично:** дефолт `.env.example` — облачная Polza (обычный DNS), там проблема не проявляется.
- **Фикс:** при работе с локальным Ollama на Linux добавить тот же `extra_hosts`-блок всем четырём воркерам.

### 5.5 Модели Ollama качаются вручную (только для локального варианта)

- **Где:** dev-флоу, вариант Б из [DEPLOYMENT.md](DEPLOYMENT.md) §2.
- **Что не так:** при переходе с облачного дефолта на локальный Ollama легко забыть `ollama pull` обеих моделей — backend стартует, а генерация упадёт на первом LLM/vision-запросе.
- **Фикс:** health-check скрипт (`make doctor`), проверяющий доступность моделей; неактуально, пока живём на облачном дефолте.

---

## 6. Мёртвый код и дубли

### 6.0 `nginx/default.conf;C` — мусорный файл

- **Где:** [nginx/](../nginx/) — рядом с рабочими `default.conf` и `prod.conf.template` лежит файл с именем `default.conf;C`.
- **Что не так:** похоже на артефакт неудачного редактирования/копирования (имя с `;C`). nginx его не читает, но файл засоряет каталог и попадает в образ через bind-mount контекст.
- **Фикс:** удалить файл (`git rm "nginx/default.conf;C"`), убедившись, что он не упомянут в compose.

### 6.4 Дублирование логики доступа к уроку

- **Где:** [routers/students.py](../backend/app/routers/students.py) (`get_lesson_for_student`, `_get_progress`), [dependencies.py](../backend/app/dependencies.py) (`get_owned_lesson`, `require_lesson_access`).
- **Что не так:** проверка enrollment/ownership продублирована в трёх местах. `require_lesson_access` объединяет обе ветки, но старые helper'ы не отрефакторены, чтобы не задеть существующее поведение.
- **Фикс:** унифицировать в `services/lesson_access.py` отдельной задачей, заменить inline-проверки в `routers/students.py` на новый dep.

### 6.5 `silero/config.py` использует устаревший Pydantic v1 API

- **Где:** [silero/config.py](../silero/config.py).
- **Что не так:** в файле `from pydantic import BaseSettings` и `class Config: env_file = ".env"`. Это Pydantic v1. Внутри проекта (backend) уже Pydantic v2.
- **Почему есть:** этот файл монтируется в **сторонний контейнер** `navatusein/silero-tts-service`, у которого свой Python и свой Pydantic. Не наш код, формально.
- **Фикс:** не трогать. Просто понимать, что это конфиг внешнего сервиса, не часть проекта.

### 6.5 ⚠ Миграция `quiz`-задач с очереди `vision` на `quiz` — breaking для запущенных тасков

- **Где:** [backend/app/tasks/quiz_pipeline.py](../backend/app/tasks/quiz_pipeline.py), [backend/app/celery_app.py](../backend/app/celery_app.py), [docker-compose.yml](../docker-compose.yml).
- **Что не так:** старая версия `generate_quiz_task` ставилась в очередь `vision`. В рамках рефакторинга все Quiz-задачи переехали на новую очередь `quiz` (новый воркер `celery_quiz`). Любые таски, успевшие попасть в `vision` ДО деплоя новой версии, останутся там лежать и никогда не будут выполнены (никто их не подберёт, потому что новый код их в `vision` уже не публикует, а старый код их подписи больше нет).
- **Почему опасно:** беззвучная потеря фоновой работы. На пользовательском фронте генерация теста просто «зависнет» (статус задачи останется `PENDING`).
- **Фикс при деплое:** перед раскаткой остановить vision-воркер, дать ему дренировать очередь до пустой (`celery -A app.celery_app inspect active --queues=vision`), убедиться что нет pending Quiz-задач в Redis, и только затем катить новую версию. Для dev-окружения — `docker-compose down -v` обнуляет очереди в Redis.

### 6.6 ⚠ `celery_quiz` с `prefork c=2` недоиспользует LLM-bound воркер при больших попытках

- **Где:** [docker-compose.yml](../docker-compose.yml) (`celery_quiz` service), [backend/app/tasks/quiz_pipeline.py](../backend/app/tasks/quiz_pipeline.py) (`grade_attempt_task`).
- **Что не так:** `grade_attempt_task` использует внутренний `ThreadPoolExecutor(max_workers=QUIZ_GRADING_WORKERS=4)` для параллельного LLM-grading'а открытых ответов. С `prefork c=2` оба процесса воркера могут параллельно проводить grading; внутри каждого — до 4 потоков (то есть пик 8 одновременных LLM-запросов). Это упирается в один Ollama-инстанс (~1-2 параллельных запроса эффективно).
- **Почему опасно:** при большой нагрузке (много студентов сдают эссе одновременно) Ollama станет узким местом и часть запросов получит таймаут/`needs_review=true` после fail-чтения LLM.
- **Фикс при росте нагрузки:** перейти на `--pool=gevent --concurrency=N` (греет один процесс, но даёт честную async-конкурентность); либо снизить `QUIZ_GRADING_WORKERS` до 1-2 и поднять `concurrency`; либо вынести LLM за Ollama (YandexGPT / vLLM). Решение откладывается до фактических жалоб — текущая конфигурация ок для одиночных классов до ~30 студентов.

### 6.7 `multiple_choice` оценивается только по Jaccard, без negative marking

- **Где:** [backend/app/services/grading_service.py](../backend/app/services/grading_service.py) (`_grade_multiple_choice`).
- **Что не так:** партиальный балл вычисляется как `|∩| / |∪|`. Лишние выбранные опции уменьшают балл (через увеличение знаменателя), но «штраф за выбранное лишнее» как самостоятельная фича не реализован. Это делает MC-вопросы чуть «мягче», чем в академической традиции (где за выбранный неверный вариант снимают балл).
- **Почему не критично:** Jaccard уже даёт честное «частично верно»; `max(0, …)` гарантирует, что отрицательного балла никогда не будет даже при пустом или сломанном ответе.
- **Фикс по запросу:** добавить флаг `Quiz.negative_marking:bool` и альтернативную формулу в `_grade_multiple_choice`. Не делать без явного запроса от преподавателей — Jaccard покрывает кейсы достаточно.

### 6.9 GC старых версий `quiz_questions` не реализован

- **Где:** [backend/app/models/quiz.py](../backend/app/models/quiz.py), [backend/app/services/quiz_service.py](../backend/app/services/quiz_service.py).
- **Что не так:** при `insert-on-write` каждое редактирование/regenerate создаёт новую строку (`id, version+1`), а старая остаётся в таблице с `superseded_at != NULL`. Очистки нет — раз пинами в `quiz_attempts.questions_snapshot` могут пользоваться даже очень старые попытки. На длинной дистанции (преподаватель крутит regenerate несколько раз в день) таблица будет распухать.
- **Почему не критично сейчас:** payload-строки маленькие, индекс `ix_quiz_questions_current` partial → запросы остаются быстрыми. Storage-объём минимален относительно медиа.
- **Фикс по запросу:** периодический джоб (Celery beat) который удаляет строки с `superseded_at < now() - retention` ПРИ УСЛОВИИ, что ни один `quiz_attempts.questions_snapshot.pointers` на них не ссылается. Проверку «никакая попытка не пинит» сделать через `NOT EXISTS (SELECT 1 FROM quiz_attempts WHERE questions_snapshot @> jsonb_build_object('pointers', jsonb_build_array(jsonb_build_object('question_id', qq.id::text, 'version', qq.version))))` или вспомогательный индекс на `pointers`.

### 6.10 Legacy full-snapshot формат `quiz_attempts.questions_snapshot` не мигрируется

- **Где:** [backend/app/services/quiz_service.py](../backend/app/services/quiz_service.py) (`resolve_snapshot`), [backend/alembic/versions/e1f2a3b4c5d6_quiz_polymorphic.py](../backend/alembic/versions/e1f2a3b4c5d6_quiz_polymorphic.py).
- **Что не так:** до перехода на pointer-снимки попытки писали полный snapshot вида `{"version": 1, "questions": [{"id", "payload", ...}]}`. Резолвер ожидает `{"version": 1, "pointers": [...]}`. На уже существующих in-progress попытках со старым форматом `snapshot_pointers(...)` вернёт пустой список → битый `BrokenSnapshotError`/пустые ответы.
- **Почему не критично сейчас:** dev-окружение `docker-compose down -v` обнуляет данные; новых попыток в старом формате не создаётся.
- **Фикс при выкатке в прод с историей:** доп. миграция, которая по каждой записи `quiz_attempts` с `questions_snapshot.questions` собирает соответствующие `(id, version=1)` строки из `quiz_questions` (или текущую current-версию) и пересохраняет `questions_snapshot` как pointer-формат. Альтернатива — добавить fallback-ветку в `resolve_snapshot` для обоих форматов, но это сохраняет техдолг навсегда.

### 6.8 `lesson_progress.quiz_score:Float` остаётся legacy после переезда на attempts

- **Где:** [backend/app/models/enrollment.py](../backend/app/models/enrollment.py) (`LessonProgress.quiz_score`), [backend/app/tasks/quiz_pipeline.py](../backend/app/tasks/quiz_pipeline.py) (`_mark_lesson_progress_if_passed`).
- **Что не так:** источник правды по результатам теста теперь — `QuizAttempt` (с историей попыток и `Decimal score`), но старое поле `lesson_progress.quiz_score:float` всё ещё обновляется как «best-attempt» агрегат, чтобы не ломать обратную совместимость и сохранять простую сортировку для UI-агрегатов.
- **Почему не критично:** значение всегда соответствует best-attempt; рассинхронизации не возникает, потому что и фон (Celery `grade_attempt_task`), и синхронный submit пишут через одну и ту же функцию-аналог.
- **Фикс по запросу:** удалить колонку и считать best-score через подзапрос в `/quiz-results`. Сейчас это лишний код, но цена низкая.

---

## Soft delete: побочные эффекты

### — `Course.owner` может прийти `None` у архивированного/удалённого преподавателя

- **Где:** [backend/app/database.py](../backend/app/database.py) (глобальный фильтр), [backend/app/schemas/course.py](../backend/app/schemas/course.py) (`CourseOut.owner: UserOut`).
- **Что не так:** User скрыт глобально через `with_loader_criteria`. Если преподавателя soft-delete-нули, его курсы остаются в БД до purge (30 дней), но загрузка `Course.owner` отфильтрует владельца → `None` → `CourseOut` (где `owner` обязателен) может упасть при сериализации курсов такого препода.
- **Почему не критично:** отдельного эндпоинта soft-delete пользователя в проекте пока нет (анонимизация — через `soft_delete_user`-хелпер), а purge удаляет курсы препода вместе с ним. Окно проявления — только между soft-delete и purge при чужом доступе к этим курсам.
- **Фикс по запросу:** при soft-delete препода каскадно архивировать его курсы, либо сделать `CourseOut.owner` опциональным.

### — Эмбеддед Celery beat на одном воркере

- **Где:** [docker-compose.yml](../docker-compose.yml) (`celery_quiz … --beat`), [backend/app/celery_app.py](../backend/app/celery_app.py) (`beat_schedule`).
- **Что не так:** планировщик встроен в воркер `celery_quiz` (`--beat`). При нескольких репликах воркера задача `purge_soft_deleted` запустится несколько раз в сутки.
- **Почему не критично:** деплой одно-инстансный; purge идемпотентен (удаляет только просроченное, `try/except` на запись).
- **Фикс по запросу:** выделенный сервис `celery beat` (один на кластер) при горизонтальном масштабировании.

### Email-верификация: stateless-токен без отзыва и доставка best-effort

- **Где:** [backend/app/services/auth_service.py](../backend/app/services/auth_service.py) (`generate_/verify_email_verification_token`), [backend/app/tasks/email_pipeline.py](../backend/app/tasks/email_pipeline.py), [backend/app/routers/auth.py](../backend/app/routers/auth.py).
- **Что не так:**
  - Verify-токен подписан, но **не одноразовый и не отзываемый** — действует весь `EMAIL_VERIFICATION_TTL_SECONDS`, даже если письмо переотправляли. Утёкшая ссылка валидна до истечения срока.
  - Доставка письма верификации — best-effort: при недоступном брокере `send_email.delay` логируется и проглатывается, регистрация всё равно 201. Юзер остаётся неверифицированным и должен нажать resend.
  - `EMAIL_PROVIDER` поддерживает только `resend`; SendGrid-ветка — заглушка интерфейса, не реализована.
- **Почему не критично:** для подтверждения почты одноразовость не обязательна; resend всегда доступен; провайдер ретраится в очереди.
- **Фикс по запросу:** одноразовые токены через Redis-nonce (как refresh-family) при ужесточении требований; реальная реализация SendGrid-провайдера.

- **Backfill доменов в сохранённых URL после переезда `/files/*` на nginx/CDN.**
  - `video_url` (и подобные полные URL) уже лежат в БД с доменом `BASE_URL` (`http://localhost:8000`). После выставления `PUBLIC_FILES_BASE_URL` новые ссылки указывают на nginx/CDN, а старые строки остаются со старым доменом.
  - `resign_url` перенаправляет на новый домен при повторной подписи (на лету), поэтому пути, проходящие через `get_url`/`resign_url`, чинятся сами; «сырые» сохранённые URL — нет.
  - **Фикс по запросу:** одноразовая миграция данных, переписывающая префикс домена в сохранённых URL. Сознательно вынесено из задачи переезда на nginx — отдельный пункт.

---

## Расхождения код ↔ доки (текущие)

Сверка 2026-07-30: доки в `docs/` и `CLAUDE.md` приведены к коду (beat-задачи, `payment_pipeline`,
GC кешей, nginx-шаблон — исправлены на месте). Остались только исторические записи:

| Где | Что устарело | Как на самом деле |
|---|---|---|
| [DECISIONS.md](DECISIONS.md) §26 | «Polling вместо SSE» | прогресс стримится по SSE, поллинг — fallback (отмечено в ARCHITECTURE §7); запись сохранена как история решения |

---

## Карта приоритетов

Если есть один спринт на починку, разумный порядок среди открытых пунктов:

1. **1.4** — авторизованная раздача `/files/*` (per-request signed URLs). Окно в 30 мин принято для MVP, но это всё ещё главный residual-риск платного контента.
2. **5.1** — миграции при горизонтальном масштабировании (не полагаться на lifespan при multi-replica).
3. **2.5** — тихий fallback при неверном числе LLM-чанков (портит качество без сигнала пользователю).
4. **2.4** — гонка re-analyze при двух вкладках.
5. **5.4** — `extra_hosts` для воркеров (актуально только при возврате на локальный Ollama).

> Закрыто с прошлой ревизии и удалено из документа: 1.5 (SECRET_KEY без дефолта + prod-guard),
> 1.8 (лимит на распакованный .docx + lxml без entity-resolve), 2.1 (`access_code` unique),
> 2.2 (UNIQUE на `LessonProgress`), 2.8 (дисковый GC кешей),
> 3.4 (авторизованный `/stream` + X-Accel/presigned), 4.4 (константы собраны в `constants.py`),
> 4.8 (structlog + request_id), 6.1 (`utils/slide_renderer.py` удалён),
> 6.2 (`/courses` — реальная страница), 6.3 (квизы в студенческом плеере — `QuizTaker`).
> 2.7 закрыт для `video_pipeline`, но сужен и оставлен для `vision_pipeline` (см. выше).

---

## Связанные документы

- [DECISIONS.md](DECISIONS.md) — почему был выбран JWT + bcrypt + локальный storage и т.д.
- [ARCHITECTURE.md](ARCHITECTURE.md) — общая картина.
- [DEPLOYMENT.md](DEPLOYMENT.md) — секция «Production deployment — что НЕ реализовано».

## N.N. slides.py: временный файл не удаляется при regen через local_copy()

`routers/slides.py`, эндпоинт регенерации текста слайда — `local_copy()`
вызывается вручную (`image_ctx.__enter__()`) без `with`, потому что обернуть
весь остаток функции в блок было рискованно без вида всего тела функции.
Временный PNG, скачанный из S3 для vision-модели, не удаляется после запроса.
Не блокер (файлы мелкие, чистятся при пересоздании контейнера), но при частой
регенерации слайдов будет копиться мусор в /tmp контейнера backend. Починить:
отрефакторить на `with storage_service.local_copy(row.image_path) as path:`
с полным телом функции под рукой.
