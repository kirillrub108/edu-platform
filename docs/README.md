# Документация Edllm

Инженерная документация платформы **Edllm** — SaaS, который из загруженной PPTX-презентации
и текста доклада собирает озвученную видеолекцию и публикует её студентам.

> Источник истины — **код**. Доки сверяются с исходниками; расхождения отмечаются явно.
> Сгенерировано/обновлено: **2026-06-15** · обновление индекса **2026-06-21** (добавлены ONBOARDING.md, `articles/`, `marketing/`).

## С чего начать

**Новичку — начни с [ONBOARDING.md](ONBOARDING.md)**: пошаговый план на первую неделю (день за днём, топ-файлы, self-check). Дальше — по порядку:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — общая картина за 30 минут: стек, сервисы, модули, потоки,
   ключевые архитектурные решения и trade-offs. Точка входа для нового разработчика.
2. **[DATA_FLOW.md](DATA_FLOW.md)** — пошаговые end-to-end сценарии (регистрация, создание урока,
   генерация видео в двух режимах, публикация, путь студента).
3. **[AUTH_FLOW.md](AUTH_FLOW.md)** — аутентификация: httpOnly-куки + CSRF, Argon2id, ротация
   refresh-семейств, роли и гейты, email-верификация.

## Справочники

| Документ | О чём |
|---|---|
| [ONBOARDING.md](ONBOARDING.md) | Маршрут на первую неделю: что читать день за днём, топ-файлы, self-check |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Компоненты, диаграммы, границы модулей, главные решения |
| [DATA_FLOW.md](DATA_FLOW.md) | Сценарии работы данных от запроса до результата |
| [AUTH_FLOW.md](AUTH_FLOW.md) | Токены, куки, CSRF, роли, email-верификация, AI-гейтинг |
| [DECISIONS.md](DECISIONS.md) | Развёрнутое обоснование каждого архитектурного выбора (ADR-стиль) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Поднятие с нуля, переменные окружения, повседневные команды, диагностика |
| [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) | Технический долг, слабые места, расхождения код↔доки, карта приоритетов |
| [ROADMAP.md](ROADMAP.md) | Приоритизированный план: блокеры прода и тех-долг, сверенные с кодом (VERIFIED/UNVERIFIED) |
| [GROWTH.md](GROWTH.md) | Продуктовый план роста: анализ конкурентов + конкретные внедрения (привлечение/удержание преподавателей) |

## Прикладные материалы (статьи, маркетинг)

| Документ | О чём |
|---|---|
| [articles/README.md](articles/README.md) | Цикл статей про Edllm: инженерные разборы (Habr/vc.ru) + преподавательский трек |
| [marketing/youtube-content-plan.md](marketing/youtube-content-plan.md) | YouTube-playbook: позиционирование, банк болей, контент-план на первое время |

> Это просветительские/маркетинговые материалы, а не инженерная спецификация — держи их отдельно от справочников выше.

## Карта системы (коротко)

```
Browser (Nuxt 3 SPA, :3000)
   │  HTTP + JSON, httpOnly-cookie auth + CSRF
   ▼
FastAPI (:8000) ── routers (thin) → services (fat) → PostgreSQL (asyncpg)
   │                                   │
   │ .delay()                          └─ Redis (broker + auth state)
   ▼
Celery workers (sync, psycopg2):
   • video   — PPTX→MP4 пайплайн
   • vision  — vision-LLM анализ слайдов
   • quiz    — генерация/проверка тестов (+ beat: суточный purge)
   • email   — транзакционные письма
   │   внешнее: LibreOffice · pdftoppm · FFmpeg · LLM+vision (Polza AI облако по умолчанию / Ollama локально) · Silero TTS
   ▼
Local/S3 storage (PPTX, PNG, WAV, MP4)   ·   Monitoring: Prometheus/Grafana/Flower/Sentry
```

## Подсистемы и где про них читать

- **Аутентификация и роли** → [AUTH_FLOW.md](AUTH_FLOW.md)
- **Пайплайн генерации видео** (двойной thread-pool, кеш слайдов) → [ARCHITECTURE.md](ARCHITECTURE.md) §8, [DATA_FLOW.md](DATA_FLOW.md) §5–6, [DECISIONS.md](DECISIONS.md)
- **Тесты/квизы** (polymorphic JSONB, snapshot, hybrid grading) → [DECISIONS.md](DECISIONS.md) §31–33
- **Биллинг и кредиты** (план, баланс, reserve/release, YooKassa) → [ARCHITECTURE.md](ARCHITECTURE.md) §9b, [DECISIONS.md](DECISIONS.md), `app/services/billing_service.py`
- **Задания (assignments)** (сдача файлов, оценка, приватный тред) → [DATA_FLOW.md](DATA_FLOW.md) §9, [DECISIONS.md](DECISIONS.md) §36, `app/services/assignment_service.py`
- **Публикация и видимость** (course/module/lesson `is_published`, AND-правило) → [DATA_FLOW.md](DATA_FLOW.md) §7, [DECISIONS.md](DECISIONS.md) §34, `app/services/visibility_service.py`
- **Версии видео урока** (`LessonVideo`, превью → публикация версии) → [DATA_FLOW.md](DATA_FLOW.md) §5.2, [DECISIONS.md](DECISIONS.md) §35
- **Email-верификация** → [AUTH_FLOW.md](AUTH_FLOW.md) §8, [DECISIONS.md](DECISIONS.md)
- **Soft-delete + суточный purge** → [DECISIONS.md](DECISIONS.md), [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md)
- **Прогресс задач (SSE)** → `app/routers/lessons.py:progress-stream`, `composables/useProgressStream.ts`
- **Деплой и эксплуатация** (dev + prod-compose) → [DEPLOYMENT.md](DEPLOYMENT.md)

> Для повседневной работы в репозитории также см. [CLAUDE.md](../CLAUDE.md) в корне (команды,
> грабли, конвенции). Он синхронизирован с этими доками (cookie+CSRF-auth, очереди Celery,
> биллинг, prod-деплой); по аутентификации канонический источник — [AUTH_FLOW.md](AUTH_FLOW.md).
</content>
