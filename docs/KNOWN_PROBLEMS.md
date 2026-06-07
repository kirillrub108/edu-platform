# KNOWN_PROBLEMS — технический долг и слабые места

> Все известные проблемы проекта в одном месте, с предлагаемыми фиксами. Сгруппировано по категориям; внутри — по убыванию приоритета.
>
> Каждая запись содержит:
> - **Где** — файл/строка, где живёт проблема
> - **Что не так** — симптом или потенциальный сбой
> - **Почему опасно**
> - **Фикс** — конкретный шаг, который её решает

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

### 1.1 ⚠ JWT в `localStorage`

- **Где:** [frontend/src/composables/useAuth.ts](../frontend/src/composables/useAuth.ts), [useApi.ts](../frontend/src/composables/useApi.ts).
- **Что не так:** оба токена (access + refresh) хранятся в `localStorage`.
- **Почему опасно:** `localStorage` доступен любому JS на странице → XSS немедленно даёт злоумышленнику обе сессии (включая refresh на 30 дней). Любая внешняя зависимость (npm-пакет с supply-chain атакой) тоже может его прочесть.
- **Фикс:** перенести на httpOnly+Secure cookie + CSRF-токен (двойная отправка). Backend начнёт принимать токены либо из cookie, либо из `Authorization` заголовка, frontend перестанет хранить их в JS-доступном месте.

### 1.2 ⚠ Refresh-токен не используется на фронте

- **Где:** [frontend/src/composables/useApi.ts](../frontend/src/composables/useApi.ts), функция `apiFetch`.
- **Что не так:** на 401 клиент чистит **оба** токена и редиректит на `/login`. Refresh не дёргается.
- **Почему опасно:**
  - UX: пользователя выкидывает каждые 30 минут с потерей контекста (несохранённые правки в SlideTextEditor, открытый PPTX-загрузчик).
  - Security: если бы refresh-флоу был прикручен, можно было бы делать access-токены жизни 5-10 минут (вместо 30). Сейчас 30 минут — компромисс.
- **Фикс:**
  ```ts
  // useApi.ts (псевдокод)
  let refreshPromise: Promise<TokenResponse> | null = null
  catch (err) {
    if (err?.response?.status === 401 && refresh_token) {
      if (!refreshPromise) {
        refreshPromise = $fetch('/auth/refresh', { method: 'POST', body: {refresh_token} })
          .finally(() => { refreshPromise = null })
      }
      const tokens = await refreshPromise
      persistTokens(tokens)
      return $fetch(path, { ...options, headers: { Authorization: `Bearer ${tokens.access_token}` } })
    }
    // ... existing logout flow
  }
  ```
  Обязательно single-flight (`refreshPromise`) — иначе несколько параллельных 401 устроят гонку refresh-токенов, и часть запросов будет выкинута.

### 1.3 ⚠ `bcrypt(sha256(password))` — уязвимо к password shucking

- **Где:** [backend/app/services/auth_service.py:13](../backend/app/services/auth_service.py).
- **Что не так:** пароль перед bcrypt хешируется sha256 (чтобы обойти 72-байтный лимит bcrypt). Это превращает любой пароль в 32-байтный SHA-256 digest.
- **Почему опасно:** если злоумышленник получит отдельную базу sha256-хешей этих же паролей (с другого сервиса), он сразу имеет «плоский» bcrypt-вход — брутфорс упрощается. Это известный анти-паттерн.
- **Фикс — два варианта:**
  - **Простой:** ограничить `password: str = Field(min_length=6, max_length=72)` в `UserRegister` и убрать `sha256`-обёртку. Минус: пользователи не могут вводить эмодзи-пароли длиннее 18 символов.
  - **Правильный:** перейти на argon2id через `passlib[argon2]` или `argon2-cffi`. Изменить `hash_password`/`verify_password` чтобы пробовали оба алгоритма (для миграции старых юзеров).

### 1.4 ⚠ `/files/*` отдаётся без авторизации

- **Где:** [backend/app/main.py:161](../backend/app/main.py) — `app.mount("/files", StaticFiles(...))`.
- **Что не так:** любой со ссылкой на `http://host:8000/files/videos/<lesson>.mp4` может скачать файл, не будучи ни преподавателем-владельцем, ни enrolled-студентом. То же — про PNG слайдов в `lessons/<id>/slides/`.
- **Почему опасно:** утечка контента курса. Особенно критично для платных курсов в будущем.
- **Фикс:**
  - Простой: добавить авторизованный proxy-эндпоинт `GET /api/v1/files/{relative_path}`, который проверяет права и затем стримит файл (через `FileResponse`).
  - Лучший: presigned URLs (если перейти на S3 — встроено). Каждый раз при возврате `video_url` или `image_url` генерировать short-lived подпись.

### 1.5 SECRET_KEY имеет дефолт

- **Где:** [backend/app/config.py:25](../backend/app/config.py) — `SECRET_KEY: str = "change-me"`.
- **Что не так:** если кто-то забыл поменять `.env`, JWT будут подписаны паролем `change-me`. Любой, кто это знает, сможет выписать себе токен с любой ролью.
- **Фикс:** убрать дефолт — `SECRET_KEY: str` (без значения), pydantic-settings будет fail-fast если переменная не задана.

### 1.6 Refresh-токен не отзывается

- **Где:** [backend/app/routers/auth.py:refresh](../backend/app/routers/auth.py).
- **Что не так:** старый refresh после `POST /auth/refresh` остаётся валидным до своего `exp`. Logout на фронте только чистит localStorage, на сервере токен живёт.
- **Почему опасно:** если refresh утёк (через тот же localStorage XSS) — атакующий может пользоваться им 30 дней, и `logout` пользователя не помогает.
- **Фикс:** добавить колонку `users.token_version: int = 0`. При выписке токенов класть `tv: user.token_version` в payload. В `decode_token` для refresh-типа сравнивать с текущим значением. `POST /auth/logout` инкрементирует `token_version`. Все refresh-токены этого пользователя инвалидируются.

### 1.7 Нет rate-limiting

- **Где:** весь backend.
- **Что не так:** brute-force атаки на `/auth/login` ничем не ограничены. Атакующий может перебирать пароли с одного IP с любой скоростью.
- **Фикс:** `slowapi` (расширение для FastAPI). Базово: на `/auth/login` — 5 запросов в минуту с одного IP. Также обязательно на `/auth/refresh`.

### 1.8 Загрузка `.docx` через `python-docx` — потенциально XXE / XML-bomb

- **Где:** [backend/app/routers/uploads.py:_extract_docx_text](../backend/app/routers/uploads.py).
- **Что не так:** `python-docx` парсит XML внутри docx стандартным `xml.etree.ElementTree`. Хотя XXE по умолчанию выключен в lxml/etree, billion-laughs (XML-bomb) всё ещё возможен.
- **Почему опасно:** теоретически загрузка спецально-составленного docx-файла может выжрать всю память backend.
- **Фикс:** использовать `defusedxml` или ограничить размер уже на этапе чтения (сейчас `MAX_SCRIPT_BYTES = 10 MB` — поможет от bomb, но не от очень эффективных).

### 1.9 CORS `allow_credentials` принудительно `False` при `*`

- **Где:** [backend/app/main.py:88](../backend/app/main.py).
- **Что не так:** условие `allow_credentials=False if _allow_all else True`. Если кто-то поставит `CORS_ORIGINS=["*"]` для удобства, credentials отключатся (что корректно по CORS-спеке), но это может неожиданно сломать клиента, ожидающего credentials.
- **Фикс:** не критично; стоит просто залогировать предупреждение при `_allow_all`, чтобы было видно в логах.

---

## 2. Correctness и race conditions

### 2.1 ⚠ `access_code` курса не уникален

- **Где:** [backend/app/models/course.py](../backend/app/models/course.py) — `access_code = Column(String(20), nullable=True)` без `unique=True` или `UniqueConstraint`.
- **Что не так:** два преподавателя могут случайно сгенерировать один и тот же код (если генерация наивная — например `course.id[:8]`).
- **Почему опасно:** `enroll(access_code=...)` в [routers/students.py](../backend/app/routers/students.py) делает `select(Course).where(Course.access_code == ...)` и берёт **первого попавшегося**. Студент может попасть не на тот курс.
- **Фикс:** мирация — `op.create_unique_constraint("uq_courses_access_code", "courses", ["access_code"])`. Дополнительно валидация при PUT — если код уже занят, вернуть 409.

### 2.2 `LessonProgress` не имеет UNIQUE constraint

- **Где:** [backend/app/models/enrollment.py:LessonProgress](../backend/app/models/enrollment.py).
- **Что не так:** теоретически можно создать несколько `LessonProgress` записей на пару `(enrollment_id, lesson_id)`. Сейчас в коде защита через `_get_progress` (если уже есть — переиспользует), но это race-уязвимо: два одновременных POST могут оба пройти проверку «нет записи» и оба создать.
- **Фикс:** добавить `UniqueConstraint("enrollment_id", "lesson_id", name="uq_progress_enrollment_lesson")` в `__table_args__`. Тогда второй insert упадёт с IntegrityError.

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

### 2.6 `task_id` пропадает при перезапуске Redis

- **Где:** [backend/app/celery_app.py](../backend/app/celery_app.py) — `backend=settings.REDIS_URL`.
- **Что не так:** Celery result backend = Redis. После перезапуска Redis (или `flushdb`) `AsyncResult(task_id).status` возвращает `PENDING` для всех завершённых задач (потому что Redis их не помнит). Frontend думает, что задача только что началась, и продолжает поллить.
- **Фикс:** использовать persistent backend для результатов (postgres через `db+...`). Или хранить результат пайплайна в `lesson.status` (уже делается) и не полагаться на Celery result.

### 2.7 `finally rmtree(work_dir)` стирает post-mortem

- **Где:** [backend/app/tasks/video_pipeline.py](../backend/app/tasks/video_pipeline.py), [vision_pipeline.py](../backend/app/tasks/vision_pipeline.py).
- **Что не так:** при падении задачи `finally` удаляет всю временную директорию `storage/video_jobs/<lesson_id>/`. Промежуточные PNG, WAV, log нельзя посмотреть.
- **Фикс:** при `error` сохранять директорию (пометить `lesson.status = error`, не удалять); удалять только при `published`. Можно ограничить TTL — крон-задача удаляет старше 7 дней.

### 2.8 Кеш слайдов растёт бесконечно

- **Где:** [backend/app/services/video_service.py:_pptx_cache_key](../backend/app/services/video_service.py), `summaries_cache` в `vision_analysis.py`.
- **Что не так:** у обоих кешей нет TTL и нет evict-стратегии. Каждый уникальный PPTX → ~5MB PNG в `slides_cache/`. Каждый PNG → ~2KB summary в `summaries_cache/`. За месяц активной работы — гигабайты.
- **Фикс:** простой LRU по mtime, удалять файлы старше 30 дней крон-задачей. Или периодически `find -atime +30 -delete` в cron.

### 2.9 Журнал оценок: pre-grade не поддерживается

- **Где:** [backend/app/routers/gradebook.py](../backend/app/routers/gradebook.py), [frontend/src/pages/courses/[id]/gradebook.vue](../frontend/src/pages/courses/[id]/gradebook.vue).
- **Что не так:** PATCH `/courses/{id}/progress/{progress_id}` работает только по уже существующей записи `lesson_progress`. Если студент ещё не открывал/не проходил урок, `progress_id == null` — преподаватель не может выставить балл «авансом»: ячейка нередактируема, эндпоинт даст 404 на чужой/несуществующий `progress_id`. Это сознательное продуктовое ограничение, чтобы не плодить пустые записи прогресса и не размывать семантику `is_completed`/`completed_at`.
- **Почему это ОК сейчас:** учитель оценивает реальное прохождение, а не «авансом»; UI явно сообщает через прочерк «—» и tooltip, что студент не проходил урок.
- **Фикс (если потребуется):** добавить отдельный POST `/courses/{id}/lessons/{lesson_id}/progress` для idempotent upsert записи прогресса с пустым `quiz_score` + ручным баллом; UI заменит нередактируемый прочерк на «Выставить балл» по таким ячейкам.

---

## 3. Performance и масштабирование

### 3.1 Один Celery worker на всё

- **Где:** [docker-compose.yml](../docker-compose.yml) — `celery_worker` командой `-c 2`.
- **Что не так:** обе задачи (`generate_video_lesson` и `analyze_presentation_task`) идут в одну очередь. Когда vision-анализ занимает все 2 слота — генерация видео простаивает.
- **Фикс:** разделить на 2 очереди:
  ```python
  # celery_app.py
  celery_app.conf.task_routes = {
      "app.tasks.video_pipeline.*": {"queue": "video"},
      "app.tasks.vision_pipeline.*": {"queue": "vision"},
  }
  ```
  И запускать два worker'а:
  ```yaml
  celery_video:    command: celery ... -Q video -c 2
  celery_vision:   command: celery ... -Q vision -c 1
  ```

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

### 3.4 `StaticFiles` через FastAPI отдаёт большие MP4

- **Где:** [backend/app/main.py:161](../backend/app/main.py).
- **Что не так:** видео раздаются ASGI-сервером uvicorn, который не оптимизирован для крупных файлов. Каждый просмотр студента нагружает Python-процесс.
- **Фикс:** в проде — nginx с `try_files` и `X-Accel-Redirect`, либо CDN перед S3.

### 3.5 LibreOffice тяжёлый и единственный

- **Где:** [backend/app/services/video_service.py:convert_pptx_to_images](../backend/app/services/video_service.py).
- **Что не так:** LibreOffice — это толстое C++-приложение, медленный старт (~5 сек на каждый запуск), нестабилен на сложных PPTX. Зависимость от его профиля (`_lo_profile/`) добавляет ещё накладных расходов.
- **Фикс — не быстрый, но идейно:**
  - Запускать LibreOffice как отдельный демон-сервис (libreoffice headless `--accept`) и общаться через UNO API.
  - Или вынести в отдельный микросервис `pptx-renderer` (отдельный контейнер, REST API).

### 3.6 `summarize_presentation` — `Semaphore(4)` фиксированно

- **Где:** [backend/app/services/vision_analysis.py:_SUMMARY_CONCURRENCY](../backend/app/services/vision_analysis.py).
- **Что не так:** магическое число. На GPU-сервере можно безопасно ставить 8-16, на слабом CPU-хосте даже 4 могут OOM'нуть Ollama.
- **Фикс:** переменная окружения `VISION_CONCURRENCY=4` с дефолтом.

### 3.7 Два thread-pool в одной задаче — потенциальная контентность

- **Где:** [backend/app/tasks/video_pipeline.py:217-251](../backend/app/tasks/video_pipeline.py).
- **Что не так:** `tts_pool=4` + `enc_pool=3` = 7 одновременных потоков **на одну задачу**. С двумя prefork worker'ами Celery — до 14 потоков → CPU contention с LibreOffice (одной задачи) и другими процессами.
- **Фикс:** свести оба пула к одному thread-pool с приоритетами; либо сделать константы env-зависимыми.

### 3.8 Pre-render слайдов не делается на этапе загрузки PPTX

- **Где:** [backend/app/routers/uploads.py:upload_pptx](../backend/app/routers/uploads.py).
- **Что не так:** при загрузке PPTX происходит **только** сохранение файла. PNG слайдов не генерятся, кеш не заполняется. Это значит — при первой генерации видео пользователь ждёт ~30 секунд только на PPTX→PNG.
- **Фикс:** отдельная Celery-задача `pre_render_slides.delay(lesson_id)` сразу после загрузки. К моменту, когда пользователь нажмёт «Создать видео», PNG уже в кеше.

---

## 4. Maintainability и developer experience

### 4.1 ⚠ Нет тестов вообще

- **Где:** `backend/tests/` пуст.
- **Что не так:** ни одного теста — ни юнит, ни интеграционного. Любой рефакторинг — слепая зона.
- **Почему опасно:** баг с `MissingGreenlet` после UPDATE Course (раздел 2 [DECISIONS.md](DECISIONS.md)) был бы пойман простым тестом `client.put('/courses/{id}/publish')`.
- **Фикс:** минимальный набор:
  ```python
  # tests/conftest.py
  @pytest.fixture
  async def client():
      transport = httpx.ASGITransport(app=app)
      async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
          yield c

  @pytest.fixture
  async def teacher_token(client):
      r = await client.post("/api/v1/auth/register", json={...})
      return r.json()["access_token"]

  # tests/test_courses.py
  async def test_publish_toggle(client, teacher_token):
      r = await client.post("/api/v1/courses/", headers={"Authorization": f"Bearer {teacher_token}"}, json={"title": "t"})
      cid = r.json()["id"]
      r2 = await client.put(f"/api/v1/courses/{cid}/publish", headers={"Authorization": f"Bearer {teacher_token}"})
      assert r2.status_code == 200
      assert r2.json()["is_published"] is True
  ```
  Достаточно ~10 тестов на критичные эндпоинты — резко поднимет уверенность при изменениях.

### 4.2 ⚠ `pages/lessons/[id].vue` — 640 строк

- **Где:** [frontend/src/pages/lessons/[id].vue](../frontend/src/pages/lessons/[id].vue).
- **Что не так:** одна страница содержит:
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

### 4.4 Магические числа разбросаны

- **Где:**
  - `_SILERO_MAX_CHARS = 800` в [tts_service.py](../backend/app/services/tts_service.py).
  - `_SLIDE_DPI = 150` в [video_service.py](../backend/app/services/video_service.py).
  - `MAX_SCRIPT_BYTES = 10 * 1024 * 1024` в [uploads.py](../backend/app/routers/uploads.py).
  - `_TTS_WORKERS = 4`, `_ENCODE_WORKERS = 3` в [video_pipeline.py](../backend/app/tasks/video_pipeline.py).
  - `_SUMMARY_CONCURRENCY = 4` в [vision_analysis.py](../backend/app/services/vision_analysis.py).
- **Что не так:** не очевидно, что эти значения связаны (например, `_TTS_WORKERS` в коде пайплайна должно совпадать с `NUMBER_OF_THREADS=4` в compose-конфиге Silero).
- **Фикс:** собрать все в `config.py` как `Settings` поля. Связанные — задокументировать в комментарии.

### 4.5 Нет линтера/форматтера/CI

- **Где:** репозиторий.
- **Что не так:** `pyrightconfig.json` есть, но не запускается автоматически. Нет `ruff`/`black`/`mypy`. Нет `eslint`/`prettier` для frontend.
- **Фикс:**
  - Backend: `ruff` + `black` через `pre-commit`.
  - Frontend: `eslint` + `prettier` (vue-eslint-parser).
  - GitHub Actions: lint → tests → build.

### 4.6 Нет CONTRIBUTING.md, нет CHANGELOG.md

- **Где:** корень.
- **Что не так:** нет единого описания, как добавлять новые эндпоинты, новые миграции, новые Celery-задачи. Нет changelog.
- **Фикс:** создать `CONTRIBUTING.md` со ссылками на этот `docs/`.

### 4.7 `StatusBadge` хардкодит список статусов

- **Где:** [frontend/src/components/StatusBadge.vue](../frontend/src/components/StatusBadge.vue).
- **Что не так:** компонент знает только перечисленные значения. Добавишь новый статус в `LessonStatus` enum в Python — компонент покажет «unknown».
- **Фикс:** вместо хардкода — мапа статусов в `composables/useStatuses.ts`, единый источник истины. Обновлять при изменении enum.

### 4.8 Логирование зашумлённое и без структуры

- **Где:** [backend/app/main.py:18-22](../backend/app/main.py).
- **Что не так:** `logging.basicConfig(level=INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")` — текстовый формат. Невозможно фильтровать в стеке вроде Loki/ELK.
- **Фикс:** structlog с JSON-выводом. Также добавить request_id в каждый лог (через middleware).

---

## 5. Operational риски

### 5.1 Миграции запускаются в `lifespan`

- **Где:** [backend/app/main.py:_ensure_schema_at_head](../backend/app/main.py).
- **Что не так:** при старте backend автоматически делает `alembic upgrade head`. В dev — удобно. В проде:
  - Если миграция тяжёлая (десятки секунд) — readiness probe k8s упадёт.
  - Если в одной реплике миграция начала выполняться, а вторая стартовала параллельно — race condition (Alembic берёт advisory lock, но всё равно).
  - Если миграция упадёт — backend не стартует, рестарт-цикл.
- **Фикс:** для прода — отдельный `kubectl Job` или CI-step с миграцией перед роллаутом backend. В коде убрать `_ensure_schema_at_head` или сделать опциональным через env-переменную `AUTO_MIGRATE=true`.

### 5.2 Нет healthcheck для celery_worker

- **Где:** [docker-compose.yml](../docker-compose.yml).
- **Что не так:** у `postgres` есть healthcheck, у остальных — нет. `celery_worker` может тихо упасть, и compose покажет его «running».
- **Фикс:**
  ```yaml
  celery_worker:
    healthcheck:
      test: ["CMD", "celery", "-A", "app.celery_app", "inspect", "ping", "-d", "celery@%h"]
      interval: 30s
      timeout: 10s
      retries: 3
  ```

### 5.3 Нет backup БД

- **Где:** инфра.
- **Что не так:** `postgres_data` — единственный volume с данными пользователей. Удалили docker volume = потеряли всё.
- **Фикс:** cron-job (хотя бы раз в день) с `pg_dump` в S3 или локальный архив.

### 5.4 `host.docker.internal` не работает на Linux по умолчанию

- **Где:** все `LLM_BASE_URL`, `VISION_OLLAMA_BASE_URL` в `.env.example`.
- **Что не так:** Linux Docker не знает `host.docker.internal`. Запуск на Linux-хосте без правок compose даст ConnectionRefused.
- **Фикс:** в `docker-compose.yml` добавить:
  ```yaml
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
  ```
  (доступно с Docker 20.10+).

### 5.5 Ollama должна быть на хосте — нет автоматизации

- **Где:** dev-флоу.
- **Что не так:** новый разработчик может пропустить шаги `ollama pull qwen3:14b` и `ollama pull qwen2.5vl:7b`. Backend стартует, но при первом запросе vision-анализ упадёт.
- **Фикс:**
  - Добавить health-check скрипт `make doctor`, который проверяет, что обе модели доступны.
  - Или вынести Ollama в compose (для CI/CD).

---

## 6. Мёртвый код и дубли

### 6.1 `utils/slide_renderer.py` — параллельный пайплайн PPTX→PNG

- **Где:** [backend/app/utils/slide_renderer.py](../backend/app/utils/slide_renderer.py).
- **Что не так:** функция `render_slides()` делает то же, что `services/video_service.py:convert_pptx_to_images` — конвертирует PPTX/PDF в PNG через LibreOffice + pdf2image. Реально нигде не вызывается (`grep -r "render_slides\|slide_renderer" backend/app` показывает только сам файл).
- **Почему есть:** видимо — раннее экспериментальное решение, потом заменено на `convert_pptx_to_images`. Не удалили.
- **Фикс:** удалить файл целиком, удалить `pdf2image` из requirements (он используется только тут).

### 6.2 `pages/courses/index.vue` пустой

- **Где:** [frontend/src/pages/courses/index.vue](../frontend/src/pages/courses/index.vue) — 8 строк.
- **Что не так:** в роутере есть `/courses`, но реальная teacher dashboard — на `/dashboard`. Эта страница либо плейсхолдер, либо забыта.
- **Фикс:** удалить файл и убедиться, что нет ссылок (`grep -r "/courses\"" frontend`). Альтернатива — редирект на `/dashboard`.

### 6.3 `LessonPlayer.vue` упрощён, нет квизов

- **Где:** [frontend/src/components/LessonPlayer.vue](../frontend/src/components/LessonPlayer.vue).
- **Что не так:** `content_type === 'quiz'` показывает «Quiz content not implemented in player yet.» Backend уже умеет генерировать квиз через `llm_service.generate_quiz`, эндпоинт `/students/lessons/{id}/quiz-result` существует, но фронта для прохождения квиза нет.
- **Фикс:** реализовать `<QuizPlayer>` компонент. Хотя бы:
  - вопросы → варианты ответа → кнопка «Ответить»;
  - подсчёт `score = correct / total`;
  - `POST /quiz-result` с этим score.

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

---

## Карта приоритетов

Если есть один спринт на починку, я бы взял в таком порядке:

1. [1.2](#12--refresh-токен-не-используется-на-фронте) — refresh-флоу. Самое заметное для UX.
2. [4.1](#41--нет-тестов-вообще) — минимальный набор интеграционных тестов на критичные эндпоинты. Защитит от регрессий при следующих фиксах.
3. [1.4](#14--files-отдаётся-без-авторизации) — авторизованная раздача файлов. Серьёзная утечка контента.
4. [3.1](#31-один-celery-worker-на-всё) — разделение очередей. Существенно улучшит ощущение скорости.
5. [2.1](#21--access_code-курса-не-уникален) — UNIQUE на access_code. Простой фикс, легко стрельнуть.
6. [5.1](#51-миграции-запускаются-в-lifespan) — вынос миграций из lifespan для прода.

---

## Связанные документы

- [DECISIONS.md](DECISIONS.md) — почему был выбран JWT + bcrypt + локальный storage и т.д.
- [ARCHITECTURE.md](ARCHITECTURE.md) — общая картина.
- [DEPLOYMENT.md](DEPLOYMENT.md) — секция «Production deployment — что НЕ реализовано».
