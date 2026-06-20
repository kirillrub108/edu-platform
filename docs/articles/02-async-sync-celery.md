# Async-API и sync-Celery в одном проекте: как мы ушли от greenlet-дедлоков

> **Площадка:** Habr · **Хабы:** Python, Backend, FastAPI, Celery, PostgreSQL · **Время чтения:** ~10 мин

**TL;DR.** FastAPI у нас полностью на `asyncpg`/`AsyncSession`, а Celery работает в prefork-режиме, где асинхронный драйвер БД ломается на greenlet-ошибках. Мы провели жёсткую границу: API живёт в async-мире, таски — в синхронном (`psycopg2`), а URL для второго выводится из единственного `DATABASE_URL` через `.replace()`. Плюс две неочевидные детали, без которых это не взлетает: `eager_defaults` на моделях с `onupdate` и ре-экспорт моделей ради Alembic. Рассказываем, на каких граблях это собрано.

---

## Проблема: один драйвер, два рантайма

Хочется писать весь код одинаково — `await db.execute(...)` и там, и там. Но рантаймы разные.

FastAPI обрабатывает запрос в event loop. Здесь `asyncpg` идеален: пока один запрос ждёт БД, корутина уступает другому. А Celery в prefork — это форкнутые процессы-воркеры с обычным синхронным стеком. Запустить в них тот же `AsyncSession` поверх `asyncpg` — значит постоянно ловить `MissingGreenlet` и подвисания: async-драйвер ждёт greenlet-контекст, которого в prefork-воркере нет.

Можно было бы сделать всё синхронным — но тогда теряем неблокирующий API. Можно перевести воркеры на отдельный async event loop — но это лишний рантайм поверх prefork и куча способов выстрелить себе в ногу. Мы выбрали третье: **признать, что это два мира, и развести их явно.**

```text
   FastAPI (event loop)          Celery (prefork-воркеры)
   ───────────────────           ────────────────────────
   create_async_engine           create_engine
   AsyncSession (asyncpg)         Session (psycopg2)
   await db.execute(...)          db.execute(...)
            │                              │
            └──────────► PostgreSQL ◄──────┘
                  один DATABASE_URL
```

---

## Решение: один конфиг, две сессии

Асинхронная половина — как в любом современном FastAPI: движок, `async_sessionmaker`, зависимость `get_db()`.

```python
# backend/app/database.py
engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

Синхронная половина не заводит вторую настройку URL. Она **выводит** sync-URL из того же `DATABASE_URL`, меняя драйвер строкой:

```python
# backend/app/tasks/video_pipeline.py
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)
```

Это сознательное решение: одна каноничная переменная окружения вместо двух параллельных, которые однажды разъедутся. Тот же приём используется ещё в нескольких местах — в стартовом «реконсайлере» состояния и в шаге Alembic.

Граница закреплена даже текстом — модульным докстрингом в сервисах, которые имеют и async-, и sync-вызовы:

```python
# backend/app/services/billing_service.py
"""Async-функции вызываются из FastAPI-роутеров (AsyncSession). Celery-таски
работают на sync Session (psycopg2) и обязаны использовать sync_*-обёртки —
никогда не импортируйте async-функции в app/tasks/*."""
```

Правило «не тащи `AsyncSession` в `app/tasks/*`» звучит как занудство, но именно его нарушение возвращает greenlet-дедлок. Поэтому оно продублировано в `billing_service`, `quiz_service`, `quota_service`, `purge_pipeline`, `usage_service` — везде, где у сервиса две стороны.

---

## Грабля №1: `MissingGreenlet` прямо в сериализации ответа

Самая коварная ловушка живёт не в тасках, а в API. Возьмём модель с полем `updated_at`, которое СУБД проставляет сама на каждом апдейте:

```python
updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
)
```

После `await db.commit()` это поле в ORM-объекте помечено как «expired»: реальное значение знает только БД (его подставил сервер). Когда дальше Pydantic при сериализации ответа читает `obj.updated_at`, SQLAlchemy пытается **синхронно** сходить за ним в базу — и на async-сессии это падает с `MissingGreenlet`.

Лечится одной строкой в маппере — но её надо знать:

```python
# backend/app/models/user.py
class User(Base):
    # eager_defaults=True заставляет SQLAlchemy добавлять RETURNING к INSERT и
    # UPDATE, чтобы поля с server_default/onupdate=func.now() заполнялись
    # сразу после commit. Без этого updated_at остаётся "expired", и
    # последующее чтение (например, Pydantic при сериализации) триггерит
    # синхронный lazy-load, который роняет async-сессию с MissingGreenlet.
    __mapper_args__ = {"eager_defaults": True}
```

Размен честный: `eager_defaults` добавляет `RETURNING` к каждому `INSERT`/`UPDATE` — зато мы **никогда** не дёргаем lazy-load на async-сессии. У нас этот маппер-арг стоит на доброй дюжине моделей (`user`, `lesson`/`module`, `course`, `quiz`, `assignment`, `payment`, `credit`, `enrollment`, `comment`, …) — везде, где есть серверные дефолты по времени. Новая модель с `onupdate=func.now()`? Копируй паттерн, иначе словишь тот же `MissingGreenlet`.

---

## Грабля №2: Alembic не видит модель, которую вы не ре-экспортировали

Миграции у нас автогенерятся. Чтобы `alembic revision --autogenerate` увидел новую таблицу или enum, модель должна быть импортирована в общий неймспейс метаданных. У нас это `app/models/__init__.py`:

```python
# backend/app/models/__init__.py
from app.models.lesson import ContentType, CreationMode, Lesson, LessonStatus, Module
# ...
__all__ = [..., "Lesson", "ContentType", "LessonStatus", "CreationMode", ...]
```

Забыл дописать сюда новую модель или новый enum (`LessonStatus`, `CreationMode`, `QuizStatus`, `AccessMode`, `UserRole`, …) — автоген просто **не заметит** изменения и сгенерит пустую миграцию. А поскольку в dev миграции применяются на старте (см. ниже), беда вскроется не сразу. Поэтому правило: **новая модель → ре-экспорт в `__init__.py`**, и enum'ы туда же.

---

## Где применяются миграции — и почему бэкенд иногда не стартует

В dev мы накатываем `alembic upgrade head` прямо в lifespan FastAPI — но только под флагом:

```python
# backend/app/main.py
async def _ensure_schema_at_head() -> None:
    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("script_location", "/app/alembic")
    # тот же приём: для alembic нужен sync-URL
    cfg.set_main_option(
        "sqlalchemy.url",
        settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"),
    )
    def _upgrade() -> None:
        command.upgrade(cfg, "head")
    await asyncio.to_thread(_upgrade)

# внутри lifespan():
if settings.RUN_MIGRATIONS_ON_STARTUP:
    await _ensure_schema_at_head()
```

Два следствия, которые стоит знать заранее:

- **Поменял модель, забыл миграцию → бэкенд не поднимется.** Ошибка апгрейда логируется как `alembic_upgrade_failed` и пробрасывается дальше — старт падает. Это фича: лучше явный отказ, чем тихий дрейф схемы.
- **В проде флаг выключен.** `RUN_MIGRATIONS_ON_STARTUP=false`, а миграции едут отдельным one-shot-шагом *до* раскатки приложения. Накатывать схему внутри стартующего веб-процесса в проде — плохая идея (гонки между репликами).

Кстати, этот блок заменил старый бутстрап через `metadata.create_all`. Тот по-тихому расходился с историей миграций и потом выдавал «type already exists» на первом же `alembic upgrade head`. С тех пор — только миграции, единый источник истины по схеме.

---

## Бонус-грабля: глобальный фильтр soft-delete и `Session.get()`

Мелочь, на которой легко обжечься. Глобальный фильтр «не показывать удалённое» навешан на класс `Session`, который лежит и под `AsyncSession`. Но `Session.get()` он **не** перехватывает — поэтому в коде мы ходим через `select().where(...)`, а не `db.get(...)`, иначе можно случайно вытащить soft-deleted-строку. А Celery-воркер очистки, наоборот, осознанно отключает фильтр на конкретном запросе через `.execution_options(include_deleted=True)`.

---

## Чем это всё окупается

- **API остаётся неблокирующим**, а тяжёлые CPU/IO-задачи живут в безопасной sync-сессии — без greenlet-сюрпризов.
- **Один `DATABASE_URL`** на оба мира: нечего рассинхронизировать.
- **Строку можно сериализовать сразу после `UPDATE`** — `eager_defaults` экономит лишний round-trip и убирает целый класс падений.
- **Схема под контролем**: автоген видит модели, миграции — единственный способ менять БД, а явный отказ старта дешевле тихого дрейфа.

Главный вывод не про SQLAlchemy, а про подход: если два рантайма не дружат — не маскируйте это абстракцией, а проведите границу и закрепите её правилом, которое нельзя забыть (докстринг + тест + копипаст-паттерн). Дешевле, чем ловить `MissingGreenlet` в проде.

→ Дальше в серии: **«4 очереди, один beat и приоритеты на Redis»** — как устроена синхронная половина снаружи, на уровне воркеров.
