# AUTH_FLOW — авторизация, токены, роли

> Документ описывает текущую реализацию **как есть**. Дыры (особенно в refresh-флоу) явно помечены — не воспринимай их как «правильное поведение».

---

## 1. Схема аутентификации в одной картинке

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Browser (Nuxt SPA)                                                      │
│                                                                          │
│  localStorage:                                                           │
│   ├── access_token    (JWT, HS256, type=access, exp=30min)              │
│   └── refresh_token   (JWT, HS256, type=refresh, exp=30days)            │
│                                                                          │
│  useState('auth.user')  ← загружается через GET /auth/me               │
└──────────────┬───────────────────────────────────────────────┬──────────┘
               │ Authorization: Bearer <access_token>          │
               ▼                                               │
┌─────────────────────────────────────────────────────────────────────────┐
│ FastAPI                                                                 │
│                                                                          │
│  /auth/register, /auth/login   ← публичные                              │
│  /auth/refresh                 ← публичный, требует refresh_token       │
│  /auth/me                      ← Depends(get_current_user)              │
│  все остальные /api/v1/*       ← Depends(require_teacher/student)       │
│                                                                          │
│  dependencies.py:                                                        │
│   HTTPBearer → decode_token → DB lookup User → role check               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Что именно хранится в JWT

Оба токена — **JWT HS256**, подписаны общим `SECRET_KEY` (env), различаются только полем `type` и сроком жизни.

### Payload (одинаковый для access и refresh, плюс `type` + `exp`)

```json
{
  "sub": "uuid-of-user",
  "email": "user@example.com",
  "role": "teacher",
  "type": "access",
  "exp": 1715000000
}
```

Поля:
- `sub` — UUID пользователя (используется в `dependencies.get_current_user` для `db.get(User, UUID(sub))`).
- `email`, `role` — продублированы из БД, **информативные**, не используются для проверок (роль читается из БД заново на каждом запросе — это важно).
- `type` — `"access"` или `"refresh"`. Защита от использования refresh там, где нужен access.
- `exp` — Unix timestamp истечения. Проверяется `jwt.decode` автоматически.

### Параметры срока жизни

| Токен | Срок | Источник |
|---|---|---|
| access | 30 минут (`ACCESS_TOKEN_EXPIRE_MINUTES`) | `.env` |
| refresh | 30 дней (`REFRESH_TOKEN_EXPIRE_DAYS`) | `.env` |
| алгоритм | HS256 | хардкод в `auth_service.py` |

### Где это всё реализовано

- [backend/app/services/auth_service.py](../backend/app/services/auth_service.py) — `create_access_token`, `create_refresh_token`, `decode_token`, `hash_password`, `verify_password`.
- [backend/app/dependencies.py](../backend/app/dependencies.py) — `get_current_user`, `require_teacher`, `require_student`.

---

## 3. Хеширование пароля — `bcrypt(sha256(password))`

### Что в коде

```python
def hash_password(password: str) -> str:
    digest = hashlib.sha256(password.encode()).digest()
    return bcrypt.hashpw(digest, bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    digest = hashlib.sha256(plain.encode()).digest()
    return bcrypt.checkpw(digest, hashed.encode())
```

### Почему так

Bcrypt усекает входной пароль на 72-м байте. Длинные пароли (или пароли с многобайтными UTF-8 символами) теряют хвост → разные пароли могут получить одинаковый хеш. SHA-256 даёт 32 байта на любой вход → влезает в bcrypt'овые 72.

### Что с этим не так

Это **известный анти-паттерн**: открывает к атаке «password shucking» — если у злоумышленника есть отдельная база `sha256` хешей этих же паролей (украденная из другого сервиса), он может брутфорсить bcrypt-хеши намного быстрее, потому что внутри они 32-байтные SHA-256 digest'ы.

См. [KNOWN_PROBLEMS.md → раздел Security](KNOWN_PROBLEMS.md). Правильнее использовать **argon2id** или ограничить длину пароля при регистрации до 72 байт.

---

## 4. Регистрация — пошагово

`POST /api/v1/auth/register`

Файл: [backend/app/routers/auth.py:register](../backend/app/routers/auth.py)

1. Валидация Pydantic ([schemas/auth.py:UserRegister](../backend/app/schemas/auth.py)):
   - `email: EmailStr` — формальная проверка.
   - `password: str` — длина 6-128.
   - `full_name: str | None`.
   - `role: UserRole = UserRole.teacher` (по умолчанию).
2. `existing = await db.scalar(select(User).where(User.email == data.email))` → 400 «Email already registered», если найден.
3. Создание `User`:
   ```python
   User(
       email=data.email,
       hashed_password=hash_password(data.password),
       full_name=data.full_name,
       role=data.role,
   )
   ```
4. `db.add(user)` → `await db.commit()` → `await db.refresh(user)`.
5. Сразу выдаются токены (без отдельного логина):
   ```python
   payload = {"sub": str(user.id), "email": user.email, "role": user.role.value}
   return TokenResponse(
       access_token=create_access_token(payload),
       refresh_token=create_refresh_token(payload),
   )
   ```
6. Статус `201 Created`.

**Замечание:** регистрация автоматически авторизует пользователя. Никакой email-верификации нет.

---

## 5. Логин — пошагово

`POST /api/v1/auth/login`

1. Валидация: `UserLogin{email, password}`.
2. `db.scalar(select(User).where(User.email == data.email))` → если нет → 401 «Invalid credentials».
3. `verify_password(data.password, user.hashed_password)` → если ложь → 401.
4. `if not user.is_active` → 403 «User is inactive».
5. Возвращает пару токенов (тот же `_tokens_for(user)`).

---

## 6. Как frontend хранит и использует токены

### Хранение

[frontend/src/composables/useAuth.ts](../frontend/src/composables/useAuth.ts):

```ts
const persistTokens = (tokens: TokenResponse) => {
  if (!import.meta.client) return
  localStorage.setItem('access_token', tokens.access_token)
  localStorage.setItem('refresh_token', tokens.refresh_token)
}
```

Оба токена — в `localStorage`. **Это XSS-уязвимое хранилище**: любой инжектированный JS получит к ним доступ. См. [KNOWN_PROBLEMS.md → Security](KNOWN_PROBLEMS.md).

### Глобальный state

```ts
const user = useState<UserOut | null>('auth.user', () => null)
```

`useState('auth.user', factory)` — это встроенный Nuxt-механизм глобального реактивного синглтона. Все компоненты, вызывающие `useAuth().user`, получают одно и то же значение.

### Использование в API-клиенте

[frontend/src/composables/useApi.ts](../frontend/src/composables/useApi.ts):

```ts
const apiFetch = async <T>(path: string, options: FetchOptions = {}) => {
  const headers: Record<string, string> = { ...options.headers }
  const token = localStorage.getItem('access_token')
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    return await $fetch<T>(path, { baseURL: base, ...options, headers })
  } catch (err: any) {
    if (err?.response?.status === 401 && import.meta.client) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      await navigateTo('/login')
    }
    throw err
  }
}
```

**Важно:** на 401 клиент чистит **оба** токена и редиректит на `/login`. Refresh-токен **не используется** — даже если бы он ещё был валиден.

---

## 7. Серверная проверка токена — три слоя

[backend/app/dependencies.py](../backend/app/dependencies.py)

```python
security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)         # ← слой 1
    if payload.get("type") != "access":                     # ← слой 2
        raise HTTPException(401, "Invalid token type")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token missing subject")
    user = await db.get(User, UUID(user_id))                # ← слой 3
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    return user
```

### Слой 1 — `HTTPBearer + decode_token`
- `HTTPBearer()` парсит заголовок `Authorization: Bearer <token>` → если нет, FastAPI сам возвращает 403.
- `decode_token` ([auth_service.py](../backend/app/services/auth_service.py)):
  ```python
  def decode_token(token: str) -> dict:
      try:
          return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
      except jwt.ExpiredSignatureError:
          raise HTTPException(401, "Token expired")
      except jwt.InvalidTokenError:
          raise HTTPException(401, "Invalid token")
  ```
  Проверяет подпись и `exp` автоматически.

### Слой 2 — `type == "access"`
Защита от того, чтобы клиент не подсунул refresh-токен в `Authorization` заголовок. Refresh должен использоваться только в `/auth/refresh`, и наоборот.

### Слой 3 — DB lookup
`db.get(User, UUID(sub))` — каждое защищённое обращение делает один SELECT в БД. Это значит:
- **Изменения роли в БД применяются мгновенно** (например, изменили `role` на `student` в админке → следующий запрос вернёт 403, даже если access-токен ещё содержит `role: teacher` в payload).
- **`is_active = False` мгновенно блокирует пользователя** на следующем запросе.
- Цена: дополнительный SELECT на каждом защищённом эндпоинте. Не оптимизировано (можно было бы кешировать), но в текущем масштабе — приемлемо.

---

## 8. Проверка ролей — `require_teacher` / `require_student`

```python
async def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.teacher:
        raise HTTPException(403, "Teacher role required")
    return user

async def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.student:
        raise HTTPException(403, "Student role required")
    return user
```

### Где какие используются

| Роутер | Guard | Эндпоинты |
|---|---|---|
| `/api/v1/courses/*` | `require_teacher` | весь CRUD курсов и модулей |
| `/api/v1/lessons/*` | `require_teacher` | всё |
| `/api/v1/uploads/*` | `require_teacher` | загрузка PPTX, скриптов, видео |
| `/api/v1/slides/*` | `require_teacher` | анализ, редактирование слайдов |
| `/api/v1/students/*` | `require_student` | enroll, my-courses, complete |
| `/api/v1/auth/me` | `get_current_user` (любая роль) | — |

### Двухролевая модель — без админа

В `UserRole` enum только два значения: `teacher`, `student`. Никакой роли «admin» нет. Если понадобится — добавлять enum-значение, генерить миграцию (`alembic revision --autogenerate`).

---

## 9. Frontend middleware

### `auth.ts` — проверка авторизованности

[frontend/src/middleware/auth.ts](../frontend/src/middleware/auth.ts):

```ts
export default defineNuxtRouteMiddleware(async () => {
  if (!import.meta.client) return

  const { user, fetchMe } = useAuth()

  if (!user.value) {
    await fetchMe()
  }

  if (!user.value) {
    return navigateTo('/login')
  }
})
```

Логика:
1. Только на клиенте (SSR отключён, но всё равно guard).
2. Если `user.value` пуст (например, после refresh страницы) → дёргает `/auth/me` через `fetchMe()`.
3. Если после этого всё ещё пусто → редирект на `/login`.

`fetchMe()` ловит любые ошибки и ставит `user.value = null` — если access-токен истёк, на 401 `useApi` уже почистил localStorage, поэтому `user` остаётся пустым → middleware редиректит.

### `teacher.ts` — проверка роли

[frontend/src/middleware/teacher.ts](../frontend/src/middleware/teacher.ts):

```ts
export default defineNuxtRouteMiddleware(() => {
  if (!import.meta.client) return

  const { user } = useAuth()

  if (user.value && user.value.role !== 'teacher') {
    return navigateTo('/student/dashboard')
  }
})
```

**Замечание:** этот guard НЕ проверяет, авторизован ли пользователь — он только редиректит студентов в их кабинет, **если они каким-то образом оказались** на teacher-странице. Авторизация проверяется отдельным middleware `auth`, который должен идти **первым** в `definePageMeta({ middleware: ['auth', 'teacher'] })`.

---

## 10. Истечение access-токена — что произойдёт

Это критичный сценарий и здесь есть **дыра**. Описываю как есть.

### Текущее поведение

1. Прошло 30 минут от логина. Access-токен истёк.
2. Пользователь делает любой запрос (например, кликнул на курс).
3. Frontend (`useApi`) шлёт `Authorization: Bearer <expired-token>`.
4. Backend (`decode_token`) ловит `jwt.ExpiredSignatureError` → возвращает 401 «Token expired».
5. Frontend (`useApi`) в обработчике catch:
   ```ts
   if (err?.response?.status === 401) {
     localStorage.removeItem('access_token')
     localStorage.removeItem('refresh_token')
     await navigateTo('/login')
   }
   ```
6. **Refresh-токен в `localStorage` есть, но он не используется.** Пользователя выкидывает на `/login`, теряя текущую страницу и контекст.

### Почему это плохо

- Преподаватель работал над уроком, нажал «Сгенерировать видео» через 31 минуту после логина → его выкидывает, всё несохранённое теряется.
- Текст в `SlideTextEditor` сохраняется через debounce 500ms — но если 401 случится во время save → потеря.
- Разрыв UX каждые 30 минут.

### Эндпоинт `/auth/refresh` существует, но неинтегрирован

[backend/app/routers/auth.py:refresh](../backend/app/routers/auth.py):

```python
@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Not a refresh token")
    user_id = payload.get("sub")
    user = await db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(401, "User not found")
    return _tokens_for(user)
```

Эндпоинт работает корректно, но **никто его не вызывает с фронта**. Чтобы починить, нужно в `useApi.apiFetch` добавить interceptor:

```ts
// псевдокод
catch (err) {
  if (err?.response?.status === 401 && refresh_token) {
    const new_tokens = await fetch('/auth/refresh', { body: {refresh_token} })
    if (ok) {
      // сохранить, ретраить оригинальный запрос
    } else {
      // logout
    }
  }
}
```

С учётом одновременных запросов нужна синхронизация (single-flight), иначе несколько вкладок будут параллельно делать refresh. См. [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md).

### Дополнительно: refresh-токен не отзывается

Текущая `refresh` функция возвращает **новую** пару, но **не инвалидирует** старый refresh-токен. Это значит:
- Если refresh-токен украли — он работает 30 дней.
- Logout на фронте чистит localStorage, но не аннулирует токены на сервере.
- Нет blacklist / token versioning на пользователе.

Правильнее: хранить `refresh_token_id` или `token_version` в таблице `users`, инкрементировать при logout, в `decode_token` для refresh — сравнивать.

---

## 11. Logout

### Frontend

[useAuth.ts:logout](../frontend/src/composables/useAuth.ts):

```ts
const logout = async () => {
  if (import.meta.client) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }
  user.value = null
  await navigateTo('/login')
}
```

**Только клиентская очистка.** Сервер ничего не знает про logout — токены остаются валидными до своего `exp`.

### Серверного эндпоинта нет

Не реализован ни `/auth/logout`, ни blacklist. Если refresh-токен утёк — пострадавший должен либо ждать 30 дней, либо у админа должна быть кнопка `is_active = False`.

---

## 12. CORS и токены

В [main.py](../backend/app/main.py):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=...,
    allow_credentials=False if _allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)
```

- `allow_credentials=True` нужен только если бы токены были в cookies. Сейчас токены — в `Authorization` заголовке, технически `credentials: false` сработал бы, но `True` оставлен «на будущее».
- `allow_origins` берётся из `CORS_ORIGINS` (.env), по умолчанию `["http://localhost:3000"]`.
- При `CORS_ORIGINS=["*"]` (dev-only) `allow_credentials` принудительно ставится в `False` — это требование CORS-спецификации.

**Порядок middleware:** `CORSMiddleware` зарегистрирован **последним** в коде, что в современной Starlette означает «обернёт всё снаружи» (Starlette использует `insert(0)` в `add_middleware`). Это критично: 500-ка от `log_and_catch` идёт обратно через CORS → получает заголовки → браузер видит правильную ошибку, а не «CORS policy».

---

## 13. Self-check

После чтения этого файла должен уметь объяснить:

1. Где именно хранятся access и refresh токены и почему это уязвимость?
2. Что произойдёт, если в БД у пользователя поменять роль с teacher на student? (Ответ: следующий запрос на teacher-эндпоинт вернёт 403, потому что роль читается из БД, не из payload.)
3. Что случится через 30 минут после логина, если пользователь активно работает? (Текущее поведение: выкидывает на /login. Желаемое: автоматический refresh — не реализовано.)
4. Может ли студент зайти на teacher-эндпоинт через подмену role в payload? (Нет — payload не подделать без `SECRET_KEY`, и проверка идёт в БД.)
5. Можно ли использовать refresh-токен в `Authorization: Bearer <refresh>`? (Нет — `dependencies.get_current_user` явно проверяет `payload.type == "access"`.)
6. Что нужно сделать, чтобы реализовать proper logout? (Серверный blacklist или token versioning + эндпоинт `/auth/logout`.)

---

## Связанные документы

- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — детальный разбор security-долга.
- [DECISIONS.md](DECISIONS.md) — почему JWT, а не сессии; почему bcrypt, а не argon2.
- [DATA_FLOW.md](DATA_FLOW.md) — как auth работает в контексте конкретных сценариев.
