# Четыре очереди, один beat и приоритеты на Redis: как устроен Celery в Edllm

> **Площадка:** Habr · **Хабы:** Python, Celery, Redis, Backend, Системное программирование · **Время чтения:** ~9 мин

**TL;DR.** У нас четыре разнородные фоновые нагрузки — рендер видео, vision-разбор слайдов, генерация квизов и письма. Мы дали каждой свою очередь и свой воркер, встроили планировщик ровно в один из воркеров (иначе ежедневная задача стреляла бы дважды) и прикрутили приоритеты по тарифу пользователя. Главная тонкость — приоритеты на Redis работают «наоборот»: меньшее число важнее. Разбираем конфиг и грабли.

---

## Зачем вообще несколько очередей

Представьте одну общую очередь. Преподаватель запускает рендер 40-слайдового урока — задача на минуты. Следом другой пользователь регистрируется, и ему нужно отправить письмо с подтверждением почты — задача на секунды. В общей очереди письмо встанет **за** видео. Пользователь сидит и ждёт письмо, которого нет, потому что воркер занят FFmpeg.

Нагрузки разные не только по длительности, но и по природе:

- **video** — CPU + диск (FFmpeg, рендер слайдов), хочется параллелизм, но не слишком;
- **vision** — память + внешний vision-LLM, безопаснее держать конкуренцию низкой;
- **quiz** — генерация и грейдинг через LLM;
- **celery_email** — лёгкие сетевые задачи, которые не должны ни за кем стоять.

Поэтому — четыре очереди, по воркеру на каждую, каждый со своим `--concurrency`.

```text
                       ┌───────────► [video]  ──► celery_video   (prefork, c=2)
   FastAPI             │
   apply_async() ──► Redis ─────────► [vision] ──► celery_vision  (prefork, c=1)
                       │
                       ├───────────► [quiz]   ──► celery_quiz    (prefork, c=2, + beat)
                       │
                       └───────────► [celery_email] ─► celery_email_worker (prefork, c=2)
```

---

## Объявление очередей и роутинг

Очереди и список модулей с тасками живут в `celery_app.py`. Список `include` — критичный: таск, которого там нет, Celery просто не зарегистрирует.

```python
# backend/app/celery_app.py
celery_app = Celery(
    "edllm",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.video_pipeline",
        "app.tasks.vision_pipeline",
        "app.tasks.quiz_pipeline",
        "app.tasks.purge_pipeline",
        "app.tasks.email_pipeline",
    ],
)

celery_app.conf.update(
    task_queues=(
        Queue("video", routing_key="video"),
        Queue("vision", routing_key="vision"),
        Queue("quiz", routing_key="quiz"),
        Queue("celery_email", routing_key="celery_email"),
    ),
    task_default_queue="video",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # ... приоритеты и beat — ниже
)
```

`task_acks_late=True` + `task_reject_on_worker_lost=True` означают, что недоделанная задача при падении воркера **вернётся в очередь**, а не потеряется. Для минутного рендера видео это важно.

Правило: **добавил новый таск-модуль → впиши его в `include` И отправь в очередь, у которой есть воркер.** Иначе задача поставится, но её некому будет взять.

---

## Ровно один beat на весь кластер

Раз в сутки нужно вычищать soft-deleted-записи. Это делает периодическая задача через Celery `beat`. И здесь — правило, которое легко нарушить: **планировщик должен быть ровно один на весь кластер.** Запустишь два — задача выстрелит дважды.

Мы не поднимаем отдельный сервис-планировщик. Вместо этого `beat` встроен в один из воркеров — `celery_quiz` — флагом `--beat`:

```yaml
# docker-compose.yml
celery_video:
  command: >
    celery -A app.celery_app worker --pool=prefork
    --concurrency=2 --queues=video --hostname=video@%h --loglevel=info

celery_vision:
  command: >
    celery -A app.celery_app worker --pool=prefork
    --concurrency=1 --queues=vision --hostname=vision@%h --loglevel=info

celery_quiz:
  # --beat встраивает планировщик в этот воркер. Только ОДИН beat на кластер.
  command: >
    celery -A app.celery_app worker --beat --schedule=/tmp/celerybeat-schedule
    --pool=prefork --concurrency=2 --queues=quiz --hostname=quiz@%h --loglevel=info

celery_email_worker:
  command: >
    celery -A app.celery_app worker --pool=prefork
    --concurrency=2 --queues=celery_email --hostname=email@%h --loglevel=info
```

Само расписание — рядом, в конфиге Celery:

```python
beat_schedule={
    "purge-soft-deleted-daily": {
        "task": "purge_soft_deleted",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "quiz"},
    },
},
```

Не реплицируйте `celery_quiz` и не добавляйте `--beat` другим воркерам — это и есть тот самый «один планировщик на кластер».

---

## Приоритеты на Redis: меньше — значит важнее

Хочется, чтобы задачи платных пользователей шли вперёд бесплатных. У RabbitMQ для этого есть нативные приоритеты. У Redis — **нет**. Зато kombu умеет эмулировать их, разворачивая каждую очередь в набор под-очередей по приоритету: `video`, `video:1`, …, `video:9` — и выгребая ту, где число меньше.

Включается это тремя настройками, и пропустить любую — значит «приоритет молча игнорируется»:

```python
# backend/app/celery_app.py
broker_transport_options={
    "priority_steps": list(range(10)),     # ступени 0..9
    "sep": ":",
    "queue_order_strategy": "priority",    # без этого priority= не работает вообще
},
worker_prefetch_multiplier=1,              # без этого prefork «съест» низкий приоритет раньше
```

Ключевой и контринтуитивный момент: **на Redis меньшее число — это больший приоритет.** `0` выгребается первым, `9` — последним. Это обратно RabbitMQ, и об этом легко споткнуться. У нас это зафиксировано прямо в константах:

```python
# backend/app/constants.py
PLAN_TIER_MAP = {
    "free":    "free",
    "starter": "paid",
    "pro":     "paid",
    "school":  "paid",
}

# Redis-брокер: МЕНЬШЕЕ число — БОЛЬШИЙ приоритет (0 первым, 9 последним),
# ОБРАТНО RabbitMQ. enterprise=0 (выше всех), free=9 (ниже всех).
TIER_PRIORITY = {
    "free":       9,
    "paid":       3,
    "enterprise": 0,
}
```

Почему `prefetch_multiplier=1` обязателен? Если prefork-воркер заберёт себе сразу несколько сообщений, он может выхватить низкоприоритетное **раньше**, чем в очередь придёт высокоприоритетное — и приоритеты перестанут что-либо значить. Префетч в единицу заставляет воркера каждый раз честно выбирать самую важную задачу.

---

## Как приоритет доезжает до задачи

Число приоритета выводится из тарифа пользователя — связка `план → тариф → приоритет`:

```python
# backend/app/services/tier_service.py
def tier_for_plan(plan) -> Tier:
    key = plan.value if isinstance(plan, CreditPlan) else plan
    return Tier(PLAN_TIER_MAP.get(key, Tier.free.value))   # неизвестный план → free

def priority_for_tier(tier: Tier) -> int:
    return TIER_PRIORITY[tier.value]

async def priority_for_user(db, user_id) -> int:
    account = await billing_service.get_or_create_account(db, user_id)
    return priority_for_tier(tier_for_plan(account.plan))
```

И реальная постановка задачи рендера — приоритет передаётся в `apply_async`:

```python
# backend/app/routers/lessons.py
priority = await tier_service.priority_for_user(db, user.id)
task = generate_video_lesson.apply_async(
    args=[str(lesson.id), pptx_path, data.voice, is_regen],
    queue="video",
    priority=priority,
)
```

Тот же приём — на постановке vision-разбора слайдов (`queue="vision"`). А вот бесплатный грейдинг студенческих ответов (`grade_attempt_task`) ставится **без** приоритета — он маркетингово бесплатный, и приоритезировать его по тарифу было бы странно.

---

## Грабли, которые мы уже прошли

- **Redis ≠ RabbitMQ по приоритетам.** Меньшее число важнее. Перепутаешь порядок в `TIER_PRIORITY` — платные уедут в конец очереди.
- **`queue_order_strategy="priority"` обязателен.** Без него `priority=` молча игнорируется, и всё «работает», но без приоритетов — самый неприятный тип бага.
- **`prefetch_multiplier=1` — не косметика.** С префетчем больше 1 приоритеты на prefork ломаются.
- **Один beat.** `--beat` только в `celery_quiz`. Лишний планировщик = двойные срабатывания периодических задач.
- **`enterprise` (приоритет 0) — задел на будущее.** Сейчас ни один план на него не маппится; неизвестный план падает в `free`.
- **Новый таск — в `include` и в очередь с воркером.** Иначе его некому исполнять.

---

## Вывод

Четыре очереди — это не оверинжиниринг, а способ не дать тяжёлому видео заблокировать лёгкое письмо. Один beat — дисциплина, без которой периодика дублируется. А приоритеты на Redis — наглядный пример, где «работает как RabbitMQ» — ложная интуиция: три настройки брокера и инвертированная шкала, иначе фича тихо не включится. Самые дорогие баги тут — не падения, а молчаливое «как будто работает».

→ Дальше в серии: **«Стриминг TTS→FFmpeg через `as_completed`»** — что именно делает воркер очереди `video` внутри.
