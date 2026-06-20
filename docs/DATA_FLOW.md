# DATA_FLOW — пошаговые сценарии

> Что именно происходит между «пользователь нажал кнопку» и «увидел результат».
> Все пути — относительно `backend/app/` и `frontend/src/`.

> **⚠️ Частичная устарелость (на 2026-06-09).** Документ написан до ряда изменений:
> - **Аутентификация** теперь на httpOnly-куках + CSRF (не localStorage Bearer), пароли — Argon2id.
>   Раздел §1 ниже обновлён; полная картина — в [AUTH_FLOW.md](AUTH_FLOW.md).
> - **Прогресс задач** стримится по **SSE** (`/lessons/{id}/progress-stream`, `useProgressStream.ts`),
>   поллинг `/task-status/{id}` — fallback. Где в тексте сказано «фронт поллит каждые N сек» — читать
>   как «SSE + поллинг-fallback».
> - **Добавлено (2026-06-15):** §7 расширен публикацией модулей/уроков и правилом видимости;
>   §9 описывает задания (assignments); §5.2 учитывает версии видео (`LessonVideo`).
> - **Ещё не описаны здесь** пошагово: квизы (создание/прохождение/проверка), биллинг/списание
>   кредитов при генерации, email-верификация и AI-гейтинг, soft-delete. См.
>   [ARCHITECTURE.md](ARCHITECTURE.md) §9b и [DECISIONS.md](DECISIONS.md) §31–37.

---

## Содержание

1. [Регистрация и логин](#1-регистрация-и-логин)
2. [Создание курса, модуля, урока](#2-создание-курса-модуля-урока)
3. [Загрузка PPTX-файла](#3-загрузка-pptx-файла)
4. [Загрузка текста доклада из файла](#4-загрузка-текста-доклада-из-файла)
5. [Генерация видео — режим `presentation_and_text`](#5-генерация-видео--режим-presentation_and_text)
6. [Генерация видео — режим `presentation_auto` (vision)](#6-генерация-видео--режим-presentation_auto-vision)
7. [Публикация: курс, модуль, урок и правило видимости](#7-публикация-курс-модуль-урок-и-правило-видимости)
8. [Студент: enroll → просмотр → отметка пройденным](#8-студент-enroll--просмотр--отметка-пройденным)
9. [Задания: создание → сдача → оценка → тред](#9-задания-создание--сдача--оценка--тред)

---

## 1. Регистрация и логин

### Регистрация (teacher)

1. Пользователь открывает `/register`. Форма в [pages/register.vue](../frontend/src/pages/register.vue).
2. Заполняет email/password/full_name, выбирает роль (по умолчанию `teacher`).
3. По submit: `useAuthStore.register(...)` (Pinia) → `apiFetch('/auth/register', { method: 'POST', body: {...} })`.
4. Запрос летит на `POST /api/v1/auth/register` ([routers/auth.py](../backend/app/routers/auth.py), лимит 3/min).
5. На бэкенде:
   - `db.scalar(select(User).where(User.email == data.email))` — проверка дубля → **409** если есть.
   - `hash_password(password)` — **Argon2id** (`argon2-cffi`).
   - `db.add(User(...))` (`email_verified=False`) → `commit` → `refresh`.
   - Ставит в очередь письмо верификации (`celery_email`) с подписанным токеном (best-effort).
6. Возвращается **`UserOut`** (профиль, без токенов) со статусом 201.
7. Frontend (`useAuthStore.register`) сразу вызывает `login(email, password)` (см. ниже) → сессия поднимается.
8. Дальше middleware (`teacher.ts`/`auth.ts` — opt-in на странице) разводит teacher/student по дашбордам.
   До подтверждения email teacher может ходить по кабинету, но **AI/создание контента заблокировано**
   (`require_verified_*`, 403) — фронт показывает `VerifyEmailModal`.

### Логин

1. Форма [pages/login.vue](../frontend/src/pages/login.vue) → submit → `useAuthStore.login(email, password, rememberMe)`.
2. `POST /api/v1/auth/login` с body `{email, password, remember_me}` (лимит 5/min).
3. На бэкенде (`AuthService.login`):
   - `select(User).where(User.email == ...)` → если нет/`verify_password` неверен → **401**.
   - `not user.is_active` → 403.
   - Создаётся refresh-семейство (uuid) в Redis, минтится пара токенов; `remember_me` выбирает
     sliding-окно (14 дн vs 1 дн).
   - Сервер **выставляет три httpOnly/csrf-куки** (`_set_auth_cookies`) и отдаёт `{}`.
4. Frontend токены **не видит и не хранит** — куки httpOnly. Он лишь дёргает `/auth/me` и кладёт
   профиль в `useAuthStore.user`. CSRF-токен (`csrf_token`, non-httpOnly) `useApi` будет автоматически
   слать в `X-CSRF-Token` на мутациях.

---

## 2. Создание курса, модуля, урока

Все три эндпоинта требуют `Depends(require_teacher)`.

### Курс

1. `/courses/create` ([pages/courses/create.vue](../frontend/src/pages/courses/create.vue)) → форма с title и description.
2. `POST /api/v1/courses/` с `{title, description}`.
3. На бэкенде ([routers/courses.py:create_course](../backend/app/routers/courses.py)):
   - Валидация: `CourseCreate` (title 1-255 chars).
   - `db.add(Course(title=..., description=..., owner_id=user.id))` → commit → refresh с `attribute_names=["owner"]`.
   - Возвращает `CourseOut`.
4. Frontend получает `course.id` → `navigateTo(/courses/${id})`.

### Модуль

1. На странице курса ([pages/courses/[id].vue](../frontend/src/pages/courses/[id].vue)) — форма «+ Модуль».
2. `POST /api/v1/courses/{course_id}/modules` с `{title, order}`.
3. На бэкенде:
   - `_get_owned_course(...)` — проверка владения (404/403).
   - `db.add(Module(course_id=..., title=..., order=...))` → commit → refresh с `attribute_names=["lessons"]`.
   - Возвращает `ModuleOut` (с пустым `lessons: []`).
4. Frontend перезагружает курс через `load()`.

### Урок

1. На странице курса под каждым модулем — форма «+ Урок».
2. `POST /api/v1/lessons/` с `{title, module_id, content_type: "video", order: 0}`.
3. На бэкенде ([routers/lessons.py:create_lesson](../backend/app/routers/lessons.py)):
   - `db.get(Module, module_id)` → 404 если нет.
   - `db.get(Course, module.course_id)` → проверка `course.owner_id == user.id` → 403 иначе.
   - `db.add(Lesson(...))` → commit → refresh.
4. Frontend сразу делает `navigateTo(/lessons/${lesson.id})` — переход на главную страницу работы с уроком.

---

## 3. Загрузка PPTX-файла

1. На странице урока ([pages/lessons/[id].vue](../frontend/src/pages/lessons/[id].vue)) — `<input type="file">` принимает `.pptx,.ppt,.pdf`.
2. После выбора файла — кнопка «Загрузить».
3. Build FormData: `form.append('file', pptxFile)`, `form.append('lesson_id', id)`.
4. `POST /api/v1/uploads/pptx?lesson_id={id}` с multipart body.
5. На бэкенде ([routers/uploads.py:upload_pptx](../backend/app/routers/uploads.py)):
   - `_ext_ok(file.filename, ALLOWED_PPTX)` — проверка расширения (`.pptx`, `.ppt`, `.pdf`) → 400 если не подходит.
   - `await storage_service.save_upload(file, "pptx")`:
     - Имя файла: `{uuid4().hex}_{safe_name}` (убирает слеши).
     - Открытие файла стримом (`aiofiles`), запись чанками по 1MB в `/app/storage/pptx/{name}`.
     - Возвращает relative path `pptx/{name}`.
   - Если в query пришёл `lesson_id` — `db.get(Lesson, ...)` → `lesson.pptx_path = relative` → `commit()`.
   - Возвращает `{file_path, file_url}` где `file_url = BASE_URL/files/pptx/{name}`.
6. Frontend сохраняет `lesson.pptx_path = result.file_path` в локальный реактив, показывает зелёный бейдж с именем файла.

---

## 4. Загрузка текста доклада из файла

Отдельный эндпоинт, потому что не сохраняет файл целиком — только извлекает текст.

1. В разделе «Текст доклада» (manual режим) — `<input type="file">` с расширениями `.txt,.md,.markdown,.pdf,.docx,.doc,.rtf,.odt,.html,.htm`.
2. Кнопка «Извлечь текст» → `POST /api/v1/uploads/script?lesson_id={id}`.
3. На бэкенде ([routers/uploads.py:upload_script](../backend/app/routers/uploads.py)):
   - Проверка расширения (`ALLOWED_SCRIPT`).
   - `await file.read()` целиком → проверка размера (≤10 MB).
   - `_extract_script_text(filename, content)` — диспетчер по расширению:
     - `.txt/.md` → `_decode_text` (пробует utf-8-sig, utf-8, cp1251, windows-1251).
     - `.pdf` → `pypdf.PdfReader.extract_text()`.
     - `.docx` → `python-docx`, текст параграфов + ячеек таблиц.
     - `.rtf` → `striprtf.rtf_to_text`.
     - `.odt` → `odfpy`.
     - `.html/.htm` → кастомный `_HTMLTextExtractor` (HTMLParser).
     - `.doc` → fallback через LibreOffice headless `--convert-to txt`.
   - Если получился пустой текст → 400 «В файле не найден текст…».
   - Если `lesson_id` в query — `lesson.script = script` → `commit()`.
   - Возвращает `{script, chars}`.
4. Frontend подставляет `script.value = result.script` в textarea.

---

## 5. Генерация видео — режим `presentation_and_text`

Это «manual» режим: преподаватель уже загрузил PPTX и ввёл текст доклада. LLM сама нарежет текст по слайдам.

### 5.1 Запуск

1. Пользователь жмёт «Создать видео» в [pages/lessons/[id].vue](../frontend/src/pages/lessons/[id].vue).
2. Frontend:
   - `await saveScript()` — сохраняет текущее значение textarea через `PUT /lessons/{id}/script`.
   - `POST /api/v1/lessons/{id}/generate-video` с body `{voice: "xenia"}` (или другой выбранный).
3. На бэкенде ([routers/lessons.py:generate_video](../backend/app/routers/lessons.py)):
   - `_get_owned_lesson(...)` — проверка владения.
   - `pptx_path = data.pptx_path or lesson.pptx_path` — иначе 400.
   - `task = generate_video_lesson.delay(str(lesson.id), pptx_path, data.voice)` — публикация задачи в Redis.
   - `lesson.video_task_id = task.id` → commit (нужно для resume polling).
   - Возвращает `{task_id, lesson_id}`.
4. Frontend запоминает `taskId.value = res.task_id`, ставит `setInterval(pollStatus, 3000)`.

### 5.2 Что делает Celery worker

Внутри [tasks/video_pipeline.py:generate_video_lesson](../backend/app/tasks/video_pipeline.py):

1. Открывает синхронную сессию `SyncSession` (psycopg2).
2. `_set_status(lesson, processing)`.
3. `_progress("slides", 0, 1)` — публикует `update_state(state="PROGRESS", meta={...})` для polling.
4. **Этап 1 — PPTX → PNG слайды.**
   - `video_service.convert_pptx_to_images(pptx_full, slides_dir, cache_dir=slides_cache_dir)`:
     - Считает `md5(pptx_bytes)+DPI` — кеш-ключ.
     - Cache hit → возвращает уже подготовленные PNG, минуя следующие шаги.
     - Cache miss:
       - LibreOffice headless: `libreoffice --convert-to pdf` (с `_seed_lo_profile()` для эмодзи).
       - `pdftoppm -png -r 150` → `slide-1.png`, `slide-2.png`, …
       - Копирует в `cache_dir/<hash>/`.
   - `_progress("slides", N, N)`.
5. **Этап 2 — VLM саммари слайдов** (только если режим manual, `creation_mode != presentation_auto`).
   - `vision_analysis_service.summarize_presentation(image_paths, progress_cb=...)`:
     - Параллельно (`asyncio.Semaphore(4)`) запрашивает Ollama vision (`qwen2.5vl:7b`).
     - Кеш по `sha256(png_bytes)+provider+model` в `storage/summaries_cache/`.
     - Возвращает по 2-4 предложения на каждый слайд — это «alignment hints» для следующего шага.
   - `_progress("summary", k, N)` обновляется по мере готовности.
6. **Этап 3 — Split + SSML annotation.**
   - `_split_and_annotate(base_script, total_slides, slide_summaries)`:
     - Внутри: `asyncio.run(llm_service.split_and_annotate_ssml(...))`.
     - Промпт `_SSML_SYSTEM` — длинный, требует разбить текст на ровно N чанков (по числу слайдов), очистить меta-токены («Слайд 1:», буллеты), сконвертировать цифры в слова, обернуть в `<p>...</p>` + `<break time=...>`.
     - Ожидает JSON `{"chunks": ["<p>...</p>", ...]}` ровно с N элементами.
     - Если LLM вернёт неверное число чанков или невалидный JSON — fallback `_fallback_ssml` (тупо делит по предложениям).
   - `_progress("llm", 1, 1)`.
7. **Этап 4 — TTS + encoding параллельно.**
   - Создаются два thread-pool:
     - `tts_pool` — 4 worker'а, каждый отправляет HTTP-запрос на Silero (`GET http://silero-tts:9898/process?INPUT_TEXT=...&VOICE=...`).
     - `enc_pool` — 3 worker'а, каждый запускает FFmpeg `loop image + audio → .mkv segment`.
   - Цепочка через `as_completed`: как только TTS чанка K готов → сразу подаётся в encoding K. Не ждём всех TTS.
   - Внутри TTS:
     - `_strip_ssml_tags` — очистка XML-тегов (заменяет `<br>`, `</p>` пробелом перед удалением).
     - `_split_for_tts(text, max_chars=800)` — Silero падает на длинных входах; нарезка по предложениям, потом по запятым.
     - Каждый чанк → отдельный HTTP-запрос → WAV → склейка через `wave` модуль (`_concat_wav`).
   - Внутри encoding:
     - `_trim_trailing_silence` — FFmpeg `silenceremove` обрезает хвостовую тишину (порог -40 dB, минимум 0.15s); если получилось <0.1s, используется оригинал.
     - `ffprobe` → длительность аудио.
     - `ffmpeg -loop 1 -t {duration} -i image -i audio -c:v libx264 -tune stillimage -preset fast -c:a aac -b:a 192k -ar 48000` → `_seg_NNNN.mkv`.
   - `_progress("tts", k, N)` и `_progress("encoding", k, N)`.
8. **Этап 5 — Concatenation.**
   - `video_service.concatenate_segments(segment_paths, video_full)`:
     - Создаёт `_concat_list.txt` с путями.
     - `ffmpeg -f concat -safe 0 -i list -c copy -movflags +faststart {output}.mp4` — без перекодирования (быстро).
     - Удаляет промежуточные `.mkv` сегменты.
9. **Финал.**
   - Создаётся строка **`LessonVideo`** (`is_published=False`, со `voice`/`creation_mode`/подписанным `video_url`) — каждая успешная генерация добавляет новую версию, старые сохраняются (`tasks/video_pipeline.py:~618`).
   - `_set_status(lesson, published)` (один commit персистит и `LessonVideo`), SSE-событие `{"status":"published","video_url":...}`, постановка письма «видео готово» в `celery_email`.
   - Возвращает `{"status": "ok", "video_id": ..., "video_url": ...}`.
   - **Выбор активной версии:** `GET /lessons/{id}/videos` отдаёт все версии (новые сверху); `POST /lessons/{id}/videos/{video_id}/publish` помечает одну `is_published=True`, снимает остальные и синхронит `lesson.video_url` — её и видит студент. Прямая загрузка готового видео (`/upload-video`) публикуется сразу.
10. **Cleanup.**
    - `finally: rmtree(work_dir)` — удаляет `storage/video_jobs/<lesson_id>/` со всеми временными файлами.

### 5.3 Что делает frontend во время работы воркера

1. `setInterval(pollStatus, 3000)`.
2. `pollStatus` → `GET /api/v1/lessons/{id}/task-status/{task_id}`.
3. На бэкенде:
   - `AsyncResult(task_id, app=celery_app)` — забирает текущее состояние из Redis.
   - Если `state == "PROGRESS"` → `meta = result.info = {"step", "done", "total"}`.
   - Если `result.ready()` → `result.result = {"status": "ok", "video_url": ...}` или `{"status": "error", "error": ...}`.
4. Frontend:
   - При `PROGRESS` обновляет `taskMeta.value` → `PipelineStages` подсвечивает текущий шаг и прогресс.
   - При `SUCCESS` → `stopPolling()` → `await load()` (перезапрашивает урок целиком) → показывается `<video :src="lesson.video_url">`.
   - При `FAILURE` → показывает текст ошибки.

### 5.4 Resume после refresh страницы

1. На load страницы фронт делает `GET /lessons/{id}` и читает `lesson.video_task_id`.
2. Если `lesson.status === 'processing'` и есть `video_task_id` — продолжает poll'ить тот же task.
3. Если `task_id` потерялся (например, Redis перезагружен) — фолбэк на polling самого `lesson.status` через `GET /lessons/{id}` каждые 3 сек, пока не сменится с `processing`.

---

## 6. Генерация видео — режим `presentation_auto` (vision)

В этом режиме нет текста доклада. Vision LLM анализирует каждый слайд и сама пишет текст озвучки. Преподаватель потом может править его в редакторе.

### 6.1 Запуск анализа

1. Пользователь выбирает карточку «Презентация (автотекст)» в [CreationModeChooser.vue](../frontend/src/components/CreationModeChooser.vue).
2. Frontend делает `PUT /lessons/{id}` с `{creation_mode: "presentation_auto"}`.
3. Загружает PPTX (тот же flow, что в разделе 3).
4. Жмёт «Запустить анализ».
5. `POST /api/v1/lessons/{id}/analyze`.
6. На бэкенде ([routers/slides.py:analyze_lesson_slides](../backend/app/routers/slides.py)):
   - Проверка владения + `lesson.pptx_path != null` → иначе 400.
   - `lesson.creation_mode = presentation_auto`, `lesson.status = analyzing` → commit.
   - `task = analyze_presentation_task.delay(str(lesson.id), lesson.pptx_path)`.
   - `lesson.analyze_task_id = task.id` → commit.
   - Возвращает `{task_id, lesson_id, status: "analyzing"}`.
7. Frontend ставит `setInterval(pollAnalyzeStatus, 2000)` → `GET /lessons/{id}/analysis-status/{task_id}`.

### 6.2 Что делает воркер

[tasks/vision_pipeline.py:analyze_presentation_task](../backend/app/tasks/vision_pipeline.py):

1. `_set_status(analyzing)`.
2. **PPTX → PNG слайды** (тот же `convert_pptx_to_images`, тот же кеш).
3. **Удаление старых SlideText:** `session.query(SlideText).filter(...).delete()`. Идёмпотентность для повторного анализа.
4. **Сохранение PNG в storage и создание `SlideText` строк:**
   - Для каждого слайда: `_store_slide_image(...)` копирует PNG в `storage/lessons/<id>/slides/slide_NNNN.png`.
   - `db.add(SlideText(lesson_id=..., slide_number=..., generated_text="", image_path=...))`.
5. **Vision-анализ последовательно:**
   - `vision_analysis_service.analyze_presentation(image_paths, course_title, progress_cb=...)`:
     - Идёт по слайдам по одному (важно — не параллельно!), потому что промпт включает «контекст последних 3 слайдов» для связности повествования.
     - Каждый слайд → `analyze_slide(slide_image_path, slide_number, total_slides, course_title, previous_context=...)`:
       - `_encode_image` (Pillow): resize до max 1280px, JPEG quality 85, base64.
       - Запрос к Ollama (`/v1/chat/completions`) с `image_url: data:image/jpeg;base64,...` + system prompt `VISION_SYSTEM_PROMPT` (длинный, требует 150-300 слов на слайд, объяснять смысл, не пересказывать буллеты).
     - Возвращает массив текстов длины N.
   - `progress_cb(slide_number, total)` после каждого → видно во фронте.
6. **Сохранение текстов:**
   - `for row, text in zip(slide_rows, texts): row.generated_text = text or ""` → commit.
   - Если ВСЕ тексты пустые → raise RuntimeError «Vision LLM returned no text…» → catch → `_set_status(error)`.
7. **Финал:** `_set_status(ready_for_edit)` (специальный статус для этого режима).

### 6.3 Редактирование текстов слайдов

1. Когда `analysis-status` вернул `SUCCESS` или `lesson.status == 'ready_for_edit'`, фронт открывает [SlideTextEditor.vue](../frontend/src/components/SlideTextEditor.vue).
2. `GET /api/v1/lessons/{id}/slides`:
   - Бэкенд читает все `SlideText` для урока, сортирует по `slide_number`, для каждого вызывает `storage_service.get_url(image_path)`.
   - Возвращает `SlideListResponse{lesson_id, status, total, slides: [...]}`.
3. UI: слева превью PNG, справа textarea с `generated_text` или `edited_text`.
4. Изменения в textarea: `scheduleSave()` ставит таймер debounce 500ms → `persistCurrent()`.
5. `persistCurrent` → `PATCH /lessons/{id}/slides/{slide_id}` с `{edited_text}`.
6. На бэкенде:
   - Проверка владения + `slide.lesson_id == lesson_id`.
   - `slide.edited_text = data.edited_text` → commit → возвращает `SlideTextOut`.
7. Кнопка «Регенерировать LLM» для одного слайда:
   - `POST /lessons/{id}/slides/{slide_id}/regenerate`.
   - Бэкенд берёт последние 3 предыдущих слайда (по `slide_number`), составляет `previous_context`.
   - Вызывает `vision_analysis_service.analyze_slide(...)` синхронно (это HTTP-запрос на 30-60 сек — фронт показывает loader).
   - `slide.generated_text = result`, `slide.edited_text = None` → commit.

### 6.4 После редактирования — генерация видео

1. Кнопка «Генерировать видео →» в редакторе → `emit('ready')`.
2. Родитель ([lessons/[id].vue](../frontend/src/pages/lessons/[id].vue)) вызывает `generateVideo()` (тот же эндпоинт `/generate-video`).
3. В `tasks/video_pipeline.py:generate_video_lesson` ветка `use_per_slide=True`:
   - Если `creation_mode == presentation_auto` И есть `SlideText` для каждого слайда → пропускает VLM-summary и LLM-split.
   - Использует `edited_text or generated_text` напрямую, оборачивая в `<p>...</p>`.
4. Дальше — стандартный TTS + encoding пайплайн.

---

## 7. Публикация: курс, модуль, урок и правило видимости

Публикация — **три независимых флага** `is_published` на разных уровнях: `Course`, `Module`, `Lesson`.

### 7.1 Эндпоинты публикации

| Уровень | Эндпоинт | Семантика |
|---|---|---|
| Курс | `PUT /api/v1/courses/{course_id}/publish` | **toggle** (флип `is_published`) |
| Модуль | `POST /api/v1/courses/{course_id}/modules/{module_id}/publish` · `…/unpublish` | set true / false, идемпотентно |
| Урок | `POST /api/v1/lessons/{lesson_id}/publish` · `…/unpublish` | set true / false, идемпотентно |

Все за `require_teacher` + проверкой владения. На курсе используется `__mapper_args__ = {"eager_defaults": True}` → `updated_at` приходит через RETURNING сразу при commit.

### 7.2 Правило видимости (AND) — `services/visibility_service.py`

Это **единственный источник истины** по видимости для студента:

```
# доступ уже записанного студента:
lesson_visible_to_student = module.is_published AND lesson.is_published
# course.is_published гейтит ТОЛЬКО обнаружение в каталоге и новую запись (enroll / preview)
```

- Учитель-владелец **обходит** правило и видит черновики; записанный студент — только `module`/`lesson`-published цепочку, **независимо от `course.is_published`**.
- **Расцепление «каталог/enroll» vs «доступ записанного»:** снял курс с публикации → курс ушёл из каталога и `enroll` отдаёт 404, **но записанные сохраняют доступ** к опубликованным модулям/урокам (в т.ч. пройденным). Спрятать материалы у всех = снять с публикации модуль/урок. Полное удаление — отдельный архив (`Course.deleted_at` → purge), не путать с unpublish.
- Скрытие модуля/урока — **read-time эффект AND**, а не каскад: снятие публикации родителя **НЕ сбрасывает** флаги детей; опубликовал модуль снова → урок сразу виден.
- Черновик модуля/урока скрывается через **404, а не 403** (`dependencies.require_lesson_access`) — чтобы не раскрывать сам факт существования неопубликованного ресурса. 403 — только если студент не записан на курс.
- `visibility_service.visible_module_tree(course)` обрезает дерево модулей/уроков под студента, возвращая DTO (не мутируя ORM-коллекции).

### 7.3 Фронт

На странице курса ([courses/[id].vue](../frontend/src/pages/courses/[id].vue)) — кнопки публикации на курсе/модуле/уроке; карточки курса показывают статус публикации, после действия `await load()` перезагружает данные с новыми флагами. Перед снятием курса с публикации при наличии записанных (`enrollment_count > 0` из `CourseDetail`) показывается `window.confirm`: записанные сохранят доступ, новые записаться не смогут, курс уйдёт из каталога.

---

## 8. Студент: enroll → просмотр → отметка пройденным

### 8.1 Регистрация студента и enroll

1. Студент регистрируется с `role: "student"` (раздел 1).
2. Открывает `/student/dashboard` ([pages/student/dashboard.vue](../frontend/src/pages/student/dashboard.vue)).
3. Вводит код доступа курса (его выдал ему teacher через `course.access_code`).
4. `POST /api/v1/students/enroll` с body `{access_code: "..."}`.
5. На бэкенде ([routers/students.py:enroll](../backend/app/routers/students.py)):
   - `Depends(require_student)` — иначе 403.
   - `db.scalar(select(Course).where(Course.access_code == data.access_code))`.
   - Если `not course or not course.is_published` → 404.
   - Проверка дубликата `Enrollment` (по `UNIQUE(student_id, course_id)`).
   - `db.add(Enrollment(student_id=user.id, course_id=course.id))` → commit.
   - Возвращает `{enrollment_id, course_id}`.
6. Frontend: `await load()` → дёргает `/students/my-courses`.

### 8.2 Просмотр уроков

1. `GET /api/v1/students/my-courses`:
   - `select(Course).join(Enrollment).where(Enrollment.student_id == user.id).options(selectinload(Course.owner))`.
   - Возвращает список `CourseOut`.
2. Студент кликает на карточку курса → `/student/courses/{id}` ([pages/student/courses/[id].vue](../frontend/src/pages/student/courses/[id].vue)).
3. `GET /students/courses/{id}`:
   - Проверяется наличие `Enrollment` → иначе 403 (на `course.is_published` НЕ завязан).
   - `select(Course).options(selectinload(Course.owner), selectinload(Course.modules).selectinload(Module.lessons))`.
   - Возвращает `CourseDetail`, где `modules` обрезаны под видимость (`module.is_published AND lesson.is_published`) — завязки на `course.is_published` нет, поэтому доступ сохраняется и после снятия курса с публикации.
4. UI: слева sidebar с модулями/уроками, справа — `LessonPlayer`.
5. `LessonPlayer` ([components/LessonPlayer.vue](../frontend/src/components/LessonPlayer.vue)) для `content_type === 'video'` показывает `<video :src="lesson.video_url" controls>` (URL — полный, выдан бэкендом при генерации).

### 8.3 Отметка прохождения

1. Кнопка «Отметить пройденным» внизу плеера.
2. `POST /api/v1/students/lessons/{lesson_id}/complete`.
3. На бэкенде ([routers/students.py:complete_lesson](../backend/app/routers/students.py)):
   - `_get_progress(user, lesson_id, db)`:
     - Проверка `Lesson` → `Module` → `Enrollment(student_id, course_id)` → 403 если нет enrollment.
     - Ищет `LessonProgress` по `(enrollment_id, lesson_id)`. Если нет — создаёт новый и `db.flush()` (без commit).
   - `progress.is_completed = True`, `progress.completed_at = datetime.now(timezone.utc)`.
   - `await db.commit()`.
   - Возвращает `{lesson_id, completed: true}`.
4. (Аналогично работает `/students/lessons/{id}/quiz-result` с `{score: float}` — если `score >= 0.6` урок автоматически становится completed.)

---

## 9. Задания: создание → сдача → оценка → тред

Задание (`Assignment`) живёт на уроке. Модели — `models/assignment.py`; логика — `services/assignment_service.py`; роутеры — `assignment_teacher.py` (`/api/v1`) и `assignment_student.py` (`/api/v1/students`). Сущности: `Assignment` → `AssignmentSubmission` (1 на пару `enrollment×assignment`, UNIQUE) → `AssignmentAttachment` (kind=`submission`|`feedback`) и `AssignmentMessage` (приватный тред).

### 9.1 Преподаватель: создать и опубликовать

1. `POST /api/v1/lessons/{lesson_id}/assignments` с `{title, prompt, max_points, due_at?, attachments_enabled, allowed_ext?, pass_threshold?}` → `AssignmentTeacherRead`.
2. Правка — `PATCH /assignments/{id}`; публикация — `POST /assignments/{id}/publish` (`status=draft→published`), `…/unpublish` — обратно. Черновое задание студенту отдаётся как **404**.

### 9.2 Студент: сдать

1. `GET /api/v1/students/lessons/{lesson_id}/assignments` — только опубликованные + своя `my_submission` (или `null`).
2. Черновик: `PUT /assignments/{id}/submission` (`{text_content}`) — авто-создаёт сабмишн (`get_or_create_submission`, race-safe на UNIQUE). Файлы: `POST /assignments/{id}/submission/files` (multipart).
3. **Валидация вложения** (`services/file_validation_service.py` + `constants.py:ATTACHMENT_*`): расширение из whitelist → MIME-категория → magic-байты / zip-slip / zip-bomb; лимиты — per-category размер (`ATTACHMENT_CATEGORY_MAX_SIZE_MB`), число файлов (`ATTACHMENT_MAX_FILES=10`), суммарный размер (`ATTACHMENT_MAX_TOTAL_SIZE_MB`). Файл только **сохраняется** (`assignments/<submission_id>/<uuid>_<name>`), не парсится. Стрим обрывается при превышении hard-cap.
4. Сдача: `POST /assignments/{id}/submission/submit` — требует текст **или** хотя бы один файл, `status=draft→submitted`.

### 9.3 Преподаватель: оценить

1. `GET /assignments/{id}/submissions` (список со счётчиками) → `GET /submissions/{sid}` (полный вид с оценкой/фидбеком).
2. `POST /submissions/{sid}/grade` с `{points_awarded, feedback?}` — **атомарно**: нормирует `points→score` в 0..1 (`grading_service.aggregate_score`), `status→returned`, ставит `graded_at`/`graded_by`, при заданном `assignment.pass_threshold` и проходе — отмечает урок пройденным. До статуса `returned` оценка/фидбек студенту **скрыты** (видны только после возврата).
3. `POST /submissions/{sid}/reopen` (`returned→submitted`) — разрешить пересдачу; учитель может приложить файлы-фидбека (`/feedback-files`).

### 9.4 Приватный тред

`POST /submissions/{sid}/messages` (обе стороны, лимит 30/мин) — `AssignmentMessage`. Учитель видит/пишет в любой тред своих заданий, студент — только в свой сабмишн.

### 9.5 Ретеншн

Строки сабмишнов/оценок хранятся как аудит. **Файлы** вложений авто-удаляются через `ATTACHMENT_RETENTION_DAYS_AFTER_GRADED` (30 дн) после `graded_at` — суточный `purge_pipeline._purge_expired_submission_attachments` сносит файлы + записи `AssignmentAttachment`, оставляя оценку/фидбек/тред.

---

## Что важно про polling и долгие задачи

1. Все долгие фоновые задачи (`generate_video_lesson`, `analyze_presentation_task`) — это Celery tasks с `bind=True`. Они публикуют прогресс через `self.update_state(state="PROGRESS", meta={"step", "done", "total"})`.
2. Прогресс хранится в Redis. После рестарта Redis он теряется.
3. `task_id` сохраняется в `lessons.video_task_id` / `lessons.analyze_task_id` — это позволяет фронту resume polling после refresh страницы.
4. `task_id` обнуляется при финальном `_set_status(...)` (см. в `tasks/video_pipeline.py:_set_status` логику для статусов `published`, `error`, `ready_for_edit`).
5. Если задача упала с исключением — `try/except` ловит, ставит `lesson.status = error`, `finally rmtree(work_dir)` чистит временные файлы. **Файлы для post-mortem не сохраняются.**

---

## Связанные документы

- [ARCHITECTURE.md](ARCHITECTURE.md) — высокоуровневое описание системы.
- [AUTH_FLOW.md](AUTH_FLOW.md) — детали JWT, ролей, refresh-флоу.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — где у этих сценариев слабые места.
