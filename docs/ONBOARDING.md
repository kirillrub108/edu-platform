# ONBOARDING — план изучения Edllm на первую неделю

Пошаговый маршрут для нового разработчика: день за днём, что прочитать, какие файлы открыть и как проверить себя. Справочники (ARCHITECTURE, DATA_FLOW, AUTH_FLOW, DECISIONS, KNOWN_PROBLEMS, DEPLOYMENT) дают глубину — этот документ связывает их в порядок и доводит до «могу вносить изменения».

> Источник истины — **код**. Если этот план и код расходятся — верь коду и поправь план.
> Обновлено: **2026-06-21**.

---

## Прежде чем начать

Edllm — SaaS, который из **PPTX + текста лекции** собирает **озвученный видеоурок** и публикует его студентам; вокруг — курсы, квизы, задания, журнал оценок и биллинг по кредитам. Две половины: `backend/` (FastAPI + Celery, Python 3.13) и `frontend/` (Nuxt 3 SPA). Всё поднимается через Docker Compose.

Держи рядом два файла как «шпаргалки»: [../CLAUDE.md](../CLAUDE.md) (команды, грабли, конвенции) и [README.md](README.md) (индекс доков).

---

## День 0 — Подними стенд и потрогай продукт

**Цель:** рабочее окружение и общее ощущение продукта руками.

1. Прочитай [DEPLOYMENT.md](DEPLOYMENT.md) — раздел про локальный запуск и `.env`.
2. Подними стек: `docker-compose up --build` (postgres, redis, silero-tts, backend, четыре celery-воркера, frontend, мониторинг).
3. Открой и пощупай:
   - Frontend — http://localhost:3000
   - API + Swagger — http://localhost:8000/docs
   - Flower (очереди Celery) — http://localhost:5555
   - Grafana — http://localhost:3001
4. Зарегистрируйся преподавателем, создай курс, собери урок из презентации (режим «Презентация + Текст»), посмотри, как задача проходит через очередь `video`.

**Внешняя зависимость:** работающий LLM+vision-провайдер (Polza AI облако по умолчанию или локальный Ollama). Без него генерация видео упадёт на шаге LLM-нарезки/vision — это нормально для первого знакомства, см. [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md).

**Self-check:**
- Какие четыре Celery-воркера/очереди подняты и кто из них держит `beat`? (→ [../CLAUDE.md](../CLAUDE.md), `docker-compose.yml`, [../backend/app/celery_app.py](../backend/app/celery_app.py))
- Кто отдаёт `/files/*` в dev и кто в проде? (→ ARCHITECTURE / DEPLOYMENT)

---

## День 1 — Карта системы и точка входа

**Цель:** понять, как запрос проходит сквозь систему, и где границы модулей.

1. Прочитай [ARCHITECTURE.md](ARCHITECTURE.md) целиком (≈30 мин) — стек, модули backend (§5) и frontend (§6), data flow (§7), решения и trade-offs (§8).
2. Открой точку входа [../backend/app/main.py](../backend/app/main.py): порядок middleware (CORS снаружи `log_and_catch` — намеренно), регистрация роутеров, `_ensure_schema_at_head` (миграции в lifespan только в dev).
3. Открой [../backend/app/database.py](../backend/app/database.py): async-движок + `get_db()`, и глобальный фильтр soft-delete.
4. Прочитай раздел про **async-API / sync-Celery** в [DECISIONS.md](DECISIONS.md) §2 и статью-разбор [articles/02-async-sync-celery.md](articles/02-async-sync-celery.md).

**Self-check:**
- Почему Celery-таски строят отдельную sync-сессию (`+asyncpg` → `+psycopg2`), а не переиспользуют async? (→ DECISIONS §2)
- Что такое `eager_defaults=True` и какой баг он предотвращает? (→ DECISIONS §6, [../backend/app/models/user.py](../backend/app/models/user.py))
- Почему новую модель/enum надо ре-экспортировать в [../backend/app/models/__init__.py](../backend/app/models/__init__.py)?

---

## День 2 — Аутентификация и роли

**Цель:** разобраться, как устроен auth без Bearer/localStorage.

1. Прочитай [AUTH_FLOW.md](AUTH_FLOW.md) — канонический источник по auth.
2. Backend: [../backend/app/dependencies.py](../backend/app/dependencies.py) — чтение `access_token`-куки, double-submit CSRF (`X-CSRF-Token` vs `csrf_token`), `require_teacher`/`require_verified_*`, `AI_GATED_ENDPOINTS`, `require_lesson_access` (404 на черновики).
3. Backend: [../backend/app/services/auth_service.py](../backend/app/services/auth_service.py) — Argon2id, ротация refresh с Redis-«семьями» и детектом повторного использования.
4. Frontend: [../frontend/src/composables/useApi.ts](../frontend/src/composables/useApi.ts) — `credentials: 'include'`, прокидывание CSRF, **singleflight** `refreshPromise` на 401, ретрай один раз; [../frontend/src/stores/auth.ts](../frontend/src/stores/auth.ts).
5. Разбор: [articles/05-auth-csrf-ai-gating.md](articles/05-auth-csrf-ai-gating.md).

**Self-check:**
- Зачем singleflight на refresh и что сломается без него? (подсказка: детект повторного использования)
- Почему черновик отдаётся как 404, а не 403?
- Какой тест не даст выкатить AI-эндпоинт без гейта? (→ `backend/tests/integration/test_ai_gating_guard.py`)

---

## День 3 — Сердце продукта: пайплайн PPTX → видео

**Цель:** понять главную фичу от загрузки до MP4.

1. Прочитай [DATA_FLOW.md](DATA_FLOW.md) §5–6 (генерация видео в двух режимах) и §7 (публикация).
2. Открой [../backend/app/tasks/video_pipeline.py](../backend/app/tasks/video_pipeline.py): два `ThreadPoolExecutor` (TTS-пул + encode-пул), стриминг через `as_completed`, per-slide чекпоинты/resume.
3. Открой [../backend/app/services/video_service.py](../backend/app/services/video_service.py): рендер слайдов `libreoffice → pdftoppm`, кэш PNG по `md5+DPI`.
4. Посмотри провайдеров: [../backend/app/services/tts_service.py](../backend/app/services/tts_service.py) (Silero/Polza), [../backend/app/services/vision_analysis.py](../backend/app/services/vision_analysis.py) (vision вместо OCR), [../backend/app/services/llm_service.py](../backend/app/services/llm_service.py).
5. Тюнинг — [../backend/app/constants.py](../backend/app/constants.py) (`TTS_WORKERS`, `ENCODE_WORKERS`, `SLIDE_DPI`, …). Разборы: [articles/04-video-pipeline-streaming.md](articles/04-video-pipeline-streaming.md), [articles/06-local-ai-economics.md](articles/06-local-ai-economics.md).

**Self-check:**
- Почему кодирование слайда `k` стартует, не дожидаясь озвучки всех слайдов? Что будет с латентностью, если вернуть «TTS-всё → encode-всё»?
- Где меняются размеры пулов и почему `TTS_WORKERS=4`?
- Как сменить AI-провайдера на облако без правки кода?

---

## День 4 — Очереди, биллинг, квизы

**Цель:** фоновая инфраструктура и денежная логика.

1. [../backend/app/celery_app.py](../backend/app/celery_app.py): четыре очереди, `include`-список тасков, **ровно один beat** в `celery_quiz`, приоритеты на Redis (меньше = важнее). Разбор: [articles/03-celery-queues-priority.md](articles/03-celery-queues-priority.md).
2. Биллинг: [../backend/app/services/billing_service.py](../backend/app/services/billing_service.py) — `reserve → charge/release`, `CREDIT_WEIGHTS`, видео по формуле, пожизненный триал. (DECISIONS, [articles/10-teacher-who-and-pricing.md](articles/10-teacher-who-and-pricing.md))
3. Квизы и проверка: [../backend/app/services/quiz_service.py](../backend/app/services/quiz_service.py), [../backend/app/services/grading_service.py](../backend/app/services/grading_service.py); решения — [DECISIONS.md](DECISIONS.md) §31–33 (polymorphic JSONB, snapshot, hybrid grading, versioned questions).

**Self-check:**
- На Redis-брокере приоритет 0 — это «раньше» или «позже»? Какие три настройки делают `apply_async(priority=...)` рабочим?
- Почему нельзя добавить `--beat` второму воркеру?
- Сколько типов вопросов поддерживает `QuestionType` и какие из них проверяются LLM бесплатно? (→ [../backend/app/models/quiz.py](../backend/app/models/quiz.py), `grading_service.py`)
- Почему попытка теста хранит `questions_snapshot` целиком? (→ DECISIONS §32)

---

## День 5 — Видимость, задания, аналитика и первый вклад

**Цель:** дочитать прикладные подсистемы и сделать первое изменение безопасно.

1. Видимость/публикация: [../backend/app/services/visibility_service.py](../backend/app/services/visibility_service.py) — `module.is_published AND lesson.is_published`; `course.is_published` гейтит **обнаружение/новую запись**, а не доступ записанных. (DECISIONS §34)
2. Задания/комментарии/журнал: [../backend/app/services/assignment_service.py](../backend/app/services/assignment_service.py), `gradebook_service.py`, `analytics_service.py`. Разбор: [articles/08-teacher-quizzes-assignments.md](articles/08-teacher-quizzes-assignments.md).
3. Прочитай [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — где тонко и что не «фиксить» сгоряча. Сверься с [ROADMAP.md](ROADMAP.md).
4. **Сделай первый вклад** по рецепту из [../CLAUDE.md](../CLAUDE.md) (раздел Conventions): тонкий роутер → авторизация в `dependencies.py` → 1–3 вызова в `services/` → `include_router` в `main.py`. Прогоняй тесты: `docker-compose exec backend pytest -m "not slow"`.

**Self-check:**
- Что увидит уже записанный студент, если преподаватель снимет курс с публикации? А если снимет модуль?
- Куда положить новый тюнинг-параметр и почему не инлайном?
- Какие правила нельзя нарушать (async→tasks, beat, AI-гейтинг)? (→ грабли ниже)

---

## Топ-файлы, которые стоит открыть в первую неделю

| Файл | Зачем |
|---|---|
| [../backend/app/main.py](../backend/app/main.py) | сборка приложения, middleware, регистрация роутеров, миграции в lifespan |
| [../backend/app/celery_app.py](../backend/app/celery_app.py) | очереди, роутинг тасков, beat, приоритеты |
| [../backend/app/dependencies.py](../backend/app/dependencies.py) | авторизация, CSRF, AI-гейтинг, доступ к уроку |
| [../backend/app/database.py](../backend/app/database.py) | async-сессия, soft-delete фильтр |
| [../backend/app/constants.py](../backend/app/constants.py) | все тюнинг-параметры в одном месте |
| [../backend/app/tasks/video_pipeline.py](../backend/app/tasks/video_pipeline.py) | главный пайплайн (TTS→FFmpeg стриминг) |
| [../backend/app/services/billing_service.py](../backend/app/services/billing_service.py) | кредиты: reserve/charge/release |
| [../backend/app/services/visibility_service.py](../backend/app/services/visibility_service.py) | единственный источник правды по видимости |
| [../frontend/src/composables/useApi.ts](../frontend/src/composables/useApi.ts) | единый fetch-обёртка: CSRF + singleflight-refresh |
| [../frontend/src/stores/auth.ts](../frontend/src/stores/auth.ts) | каноничное состояние авторизации |

---

## Грабли первой недели (что легко сломать)

- **Не импортируй `AsyncSession`/async-функции в `app/tasks/*`** — префорк-воркер словит greenlet-дедлок. Таски только на sync-сессии. (DECISIONS §2)
- **Новая модель с `onupdate=func.now()`** → копируй `__mapper_args__ = {"eager_defaults": True}`, иначе `MissingGreenlet` при сериализации. (DECISIONS §6)
- **Новый AI-эндпоинт** → за `require_verified_*` **и** в `AI_GATED_ENDPOINTS`, иначе красный CI.
- **Новый таск** → впиши в `include=[...]` и отправь в очередь, у которой есть воркер.
- **Ровно один `beat`** на кластер (в `celery_quiz`). Не плоди.
- **Приоритеты Redis инвертированы** — меньшее число важнее; не переворачивай `TIER_PRIORITY`.
- **Видимость** — не переколачивай AND-правило инлайном, зови `visibility_service`.

---

## Карта: «какой вопрос → какой документ»

| Вопрос | Куда смотреть |
|---|---|
| Как устроена система целиком | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Как данные текут в конкретном сценарии | [DATA_FLOW.md](DATA_FLOW.md) |
| Как работает auth | [AUTH_FLOW.md](AUTH_FLOW.md) |
| Почему так, а не иначе | [DECISIONS.md](DECISIONS.md) |
| Где тонко и что не трогать | [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md), [ROADMAP.md](ROADMAP.md) |
| Как поднять/задеплоить | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Команды, конвенции, «как добавить X» | [../CLAUDE.md](../CLAUDE.md) |
| Подача продукта и инженерные разборы | [articles/README.md](articles/README.md) |

---

> Прошёл все пять дней и ответил на self-check без подсказок? Ты готов брать задачи. Если на каком-то вопросе «плывёт» — вернись к указанному файлу: ответ всегда в коде.
