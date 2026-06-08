# AUTH_FLOW — авторизация, токены, роли

> Документ описывает **текущую** реализацию как есть (проверено по коду на 2026-06-09).
> ⚠️ Раньше аутентификация работала на `Authorization: Bearer` + `localStorage` + bcrypt.
> Сейчас это **httpOnly-cookie + double-submit CSRF + Argon2id + ротация refresh-семейств**.
> Если встретишь в других доках (или в `CLAUDE.md`) описание Bearer/localStorage/bcrypt — это
> устаревшее, источник истины — код в [auth_service.py](../backend/app/services/auth_service.py),
> [dependencies.py](../backend/app/dependencies.py), [routers/auth.py](../backend/app/routers/auth.py),
> [useApi.ts](../frontend/src/composables/useApi.ts).

---

## 1. Схема аутентификации в одной картинке

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Browser (Nuxt SPA)                                                       │
│                                                                          │
│  Cookies (выставляет сервер):                                            │
│   ├── access_token   httpOnly, path=/                    (JWT, ~15 мин)  │
│   ├── refresh_token  httpOnly, path=/api/v1/auth/refresh (JWT, ~14 дн)  │
│   └── csrf_token     НЕ httpOnly, path=/   (случайные 32 байта hex)      │
│                                                                          │
│  Pinia useAuthStore.user  ← загружается через GET /auth/me              │
│  (никакие токены в JS/localStorage не хранятся)                          │
└───────────┬──────────────────────────────────────────────┬─────────────┘
            │ credentials: 'include' (куки летят сами)      │
            │ + X-CSRF-Token: <значение csrf_token>         │ на POST/PUT/PATCH/DELETE
            ▼                                               │
┌──────────────────────────────────────────────────────────────────────────┐
│ FastAPI                                                                  │
│  /auth/register, /auth/login         ← публичные, выставляют куки        │
│  /auth/refresh                       ← публичный, читает refresh-cookie  │
│  /auth/logout                        ← чистит куки + revoke в Redis      │
│  /auth/me, всё остальное /api/v1/*   ← Depends(get_current_user / ...)   │
│                                                                          │
│  dependencies.py:                                                        │
│   Cookie(access_token) → decode_token → type==access → blacklist-check   │
│     → CSRF-check (для state-changing) → DB lookup User → role/email/own  │
└──────────────────────────────────────────────────────────────────────────┘
                  │ refresh-семейства / blacklist / email-cooldown
                  ▼
              ┌────────┐
              │ Redis  │  refresh:{user_id}:{family_id} · blacklist:{jti}
              └────────┘
```

---

## 2. Хеширование пароля — Argon2id

Активный хешер — **Argon2id** (`argon2-cffi`, дефолты OWASP). Memory-hard, нет лимита 72 байта,
нет pre-hash-костылей. См. [auth_service.py](../backend/app/services/auth_service.py):

```python
from argon2 import PasswordHasher
_ph = PasswordHasher()

def hash_password(password: str) -> str:        return _ph.hash(password)
def verify_password(plain, hashed) -> bool:     # _ph.verify(), False на VerifyMismatchError
```

> Старые доки (и `## 5` в [DECISIONS.md](DECISIONS.md), и `## 3` в более ранней версии этого файла,
> и `KNOWN_PROBLEMS §1.3`) упоминают `bcrypt(sha256(password))`. **Это уже не так** — bcrypt удалён,
> весь связанный с ним техдолг (password shucking) неактуален.

---

## 3. Токены: что в них лежит и сколько живут

Оба токена — **JWT HS256**, подписаны общим `SECRET_KEY`. Различаются полем `type`, набором
claim'ов и сроком жизни.

### Access-token (claim `type=access`)
```json
{ "sub": "<user-uuid>", "email": "...", "role": "teacher",
  "jti": "<uuid>", "iat": 1715000000, "exp": 1715000900,
  "type": "access", "family_id": "<uuid>" }
```
- `jti` — нужен для blacklist при logout.
- `family_id` — привязывает access к refresh-семейству, чтобы `/auth/logout` мог отозвать семейство,
  имея только access-cookie (refresh-cookie до `/auth/logout` не доходит — он path-scoped).
- `role` информативен; реальная роль **читается из БД** на каждом запросе.

### Refresh-token (claim `type=refresh`)
```json
{ "sub": "<user-uuid>", "family_id": "<uuid>", "jti": "<uuid>",
  "iat": ..., "exp": ..., "type": "refresh" }
```

### Параметры срока жизни (`config.py`, переопределяются из `.env`)

| Параметр | Дефолт | Назначение |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | время жизни access |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 14 | sliding-окно refresh при `remember_me=true` |
| `REFRESH_TOKEN_SESSION_DAYS` | 1 | sliding-окно при `remember_me=false` |
| `REFRESH_TOKEN_ABSOLUTE_MAX_DAYS` | 90 | абсолютный потолок жизни семейства |
| `JWT_ALGORITHM` | HS256 | алгоритм подписи |

`exp` refresh-токена = `min(now + sliding_days, absolute_expires_at)` — токен не может пережить
абсолютный дедлайн семейства, даже если обойти Redis.

---

## 4. Транспорт: httpOnly-куки + double-submit CSRF

Логин/refresh выставляют три куки (`routers/auth.py:_set_auth_cookies`):

| Cookie | httpOnly | path | Назначение |
|---|---|---|---|
| `access_token` | ✅ | `/` | летит со всеми API-запросами |
| `refresh_token` | ✅ | `/api/v1/auth/refresh` | летит **только** на refresh — не утекает в обычные запросы |
| `csrf_token` | ❌ | `/` | JS читает и шлёт обратно как `X-CSRF-Token` |

`secure`/`samesite` берутся из `COOKIE_SECURE`/`COOKIE_SAMESITE` (в проде → `secure=True`).

**CSRF (double-submit):** на каждый state-changing запрос (`POST/PUT/PATCH/DELETE`)
[dependencies.py:get_current_token_payload](../backend/app/dependencies.py) сравнивает заголовок
`X-CSRF-Token` со значением cookie `csrf_token`. Не совпало / отсутствует → **403 `CSRF token invalid`**.
Атакующий с другого origin не может прочитать non-httpOnly куку → не подделает заголовок.
Есть и отдельная зависимость `check_csrf` для неаутентифицированных state-changing-эндпоинтов.

На фронте это автоматизирует [useApi.ts](../frontend/src/composables/useApi.ts): читает `csrf_token`
из `document.cookie`, добавляет `X-CSRF-Token` для мутаций (кроме `/auth/*`), и всегда шлёт
`credentials: 'include'`.

---

## 5. Refresh — ротация семейств и детект кражи

Состояние семейства лежит в Redis под `refresh:{user_id}:{family_id}`:
```json
{ "jti": "<текущий валидный jti>", "created_at": "...",
  "absolute_expires_at": "...", "sliding_days": 14 }
```

Логика `AuthService.refresh()` ([auth_service.py](../backend/app/services/auth_service.py)):
1. Декодировать refresh-токен, проверить `type==refresh`, достать `sub/family_id/jti`.
2. Прочитать запись семейства. Нет записи → **401 Session expired**.
3. `family.jti != token.jti` → **reuse detected**: запись удаляется, всё семейство сжигается
   (предполагаем, что старый токен украли) → **401 «All sessions invalidated»**.
4. Проверить абсолютный дедлайн (sliding не может его продлить).
5. Проверить, что юзер существует и активен.
6. Сминтить **новую пару**, перезаписать `jti` семейства, сбросить sliding-TTL.

Эндпоинт: `POST /api/v1/auth/refresh` — читает `refresh_token` из cookie, отдаёт `{}` и новые куки.

---

## 6. Серверная проверка токена — слои

`get_current_token_payload` ([dependencies.py](../backend/app/dependencies.py)):
1. Нет cookie `access_token` → 401 `Not authenticated`.
2. `decode_token` (подпись + exp). `type != access` → 401.
3. `jti` в `blacklist:{jti}` (Redis) → 401 `Token has been revoked`.
4. Для state-changing методов — CSRF double-submit (см. §4).

`get_current_user` поверх него:
- `select(User).where(id == sub)` — **через `select`, не `db.get`**, чтобы сработал глобальный
  soft-delete-фильтр (удалённые юзеры невидимы).
- Не найден / `is_active == False` → 401.
- Прокидывает юзера в Sentry-контекст.

---

## 7. Роли и гейты доступа

Двухролевая модель `UserRole`: **teacher** / **student** (админ-роли в БД нет).

| Зависимость | Что проверяет |
|---|---|
| `require_teacher` | роль == teacher |
| `require_student` | роль == student |
| `require_verified_teacher` | teacher **и** `email_verified` — гейт на создание/изменение контента |
| `require_verified_email` | любой залогиненный с подтверждённой почтой — гейт на AI-операции |
| `require_admin` | shared-secret в заголовке `X-Admin-Token` == `ADMIN_API_TOKEN` (биллинг-админка; пустой токен = доступ выключен) |
| `require_lesson_access` | teacher-владелец **или** записанный на курс student → `(user, lesson, is_owner)` |
| `get_owned_lesson` | урок принадлежит курсу текущего teacher (иначе 404) |

### AI-гейтинг
Каждый эндпоинт, дёргающий LLM/vision/TTS, обязан стоять за `require_verified_email` или
`require_verified_teacher`. Реестр-источник истины — `AI_GATED_ENDPOINTS` в
[dependencies.py](../backend/app/dependencies.py); тест
[test_ai_gating_guard.py](../backend/tests/integration/test_ai_gating_guard.py) падает, если добавить
AI-роут и забыть его туда внести. Проверка студенческого квиза намеренно исключена (см. DECISIONS).

---

## 8. Email-верификация

Регистрация ставит юзера с `email_verified=False` и ставит письмо в очередь (`celery_email`).

- **Токен** — stateless, подписан `itsdangerous.URLSafeTimedSerializer` (salt `email-verify`),
  TTL `EMAIL_VERIFICATION_TTL_SECONDS` = 24 ч. DB-строки нет: токен сам по себе — доказательство.
- `GET /auth/verify-email?token=…` — валидирует, ставит `email_verified=True` (идемпотентно),
  **302** на SPA `/login?verified=1` (или `verified=0&reason=expired|invalid|not_found`). Никогда не 500.
- `POST /auth/verify-email` — SPA-вариант: **одноразовое** «потребление» токена через
  `email_token_service.consume` (Redis), затем флип флага. 400 на невалидный/просроченный/использованный.
- `POST /auth/resend-verification` — повторная отправка залогиненному; per-user Redis-cooldown
  (`EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS`) поверх slowapi per-IP лимита.

На фронте непроверенному юзеру `useAiGuard` открывает `VerifyEmailModal` при клике на AI-действие.

---

## 9. Logout

- `POST /auth/logout` — best-effort: из access-cookie достаёт `jti`/`family_id`, кладёт
  `blacklist:{jti}` в Redis до естественного `exp`, удаляет refresh-семейство, **чистит все три куки**.
  Главное действие — очистка кук — выполняется всегда, даже если Redis недоступен.
- `POST /auth/logout-all` — `scan` + `delete` всех `refresh:{user_id}:*`. Уже выданные access-токены
  доживают до своего `exp` (≤ `ACCESS_TOKEN_EXPIRE_MINUTES`) — сознательный размен ради stateless-пути.

Тонкость в коде: куки чистятся на **возвращаемом** `Response`, а не на инжектированном `response`
параметре (FastAPI отдаёт именно возвращённый объект).

---

## 10. Rate limiting

`slowapi` (см. [limiter.py](../backend/app/limiter.py)) с per-route декораторами:
`register` 3/min, `login` 5/min, `refresh` 10/min, `resend-verification` 3/min. Превышение → 429
(отдельный handler в `main.py`).

---

## 11. Frontend: где живёт состояние

- [stores/auth.ts](../frontend/src/stores/auth.ts) (**Pinia** `useAuthStore`) — `user`, `isAuthenticated`,
  `isEmailVerified`, `login/register/logout/fetchMe`, флаг `verifyPromptOpen`. **Токены не хранятся** —
  они в httpOnly-куках; стор знает только профиль из `/auth/me`.
- [useApi.ts](../frontend/src/composables/useApi.ts) — единственная обёртка над fetch:
  `credentials: 'include'`, double-submit CSRF, **реактивный** refresh на 401 (singleflight
  `refreshPromise` — пачка параллельных 401 даёт ровно одну ротацию), на провал → `clearSession` + `/login`.
  `/auth/me` трактуется как «проба сессии»: 401 на нём = «аноним», без редиректа.
- Middleware: [auth.ts](../frontend/src/middleware/auth.ts) — **opt-in на странице** (не глобальный
  по дизайну), [teacher.ts](../frontend/src/middleware/teacher.ts) — выкидывает студентов из
  teacher-страниц на `/student/dashboard`, [guest.ts](../frontend/src/middleware/guest.ts) — уводит
  залогиненных с `/login`,`/register`.

---

## 12. Self-check

1. Где физически лежит access-token в браузере и почему JS не может его прочитать?
   <sub>httpOnly-cookie `access_token`, path=/. См. §4.</sub>
2. Что произойдёт, если злоумышленник переиграет уже ротированный refresh-jti?
   <sub>Reuse-detection сжигает всё семейство → 401. См. §5.</sub>
3. Почему `refresh_token`-cookie имеет `path=/api/v1/auth/refresh`, а не `/`?
   <sub>Чтобы не утекать с каждым запросом; доходит только до refresh-эндпоинта. §4.</sub>
4. Как добавить новый AI-эндпоинт, не уронив CI?
   <sub>Повесить `require_verified_email`/`require_verified_teacher` И внести в `AI_GATED_ENDPOINTS`. §7.</sub>

---

## Связанные документы
- [ARCHITECTURE.md](ARCHITECTURE.md) · [DATA_FLOW.md](DATA_FLOW.md) · [DECISIONS.md](DECISIONS.md) · [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md)
</content>
</invoke>
