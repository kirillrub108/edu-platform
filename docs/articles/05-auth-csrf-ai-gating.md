# Auth без Bearer и localStorage: httpOnly-куки, double-submit CSRF и singleflight-refresh

> **Площадка:** Habr · **Хабы:** Информационная безопасность, Веб-разработка, FastAPI, Nuxt.js, Backend · **Время чтения:** ~11 мин

**TL;DR.** Мы не храним токены в `localStorage` и не шлём `Authorization: Bearer`. Доступ — на httpOnly-куках, которые JS вообще не видит. От CSRF защищаемся double-submit-схемой (заголовок `X-CSRF-Token` обязан совпасть с не-httpOnly кукой). Протухший access-токен чинится прозрачно: на 401 фронт делает один `refresh` на всю пачку запросов (singleflight) и повторяет исходный. Refresh-токены живут в Redis-«семьях» с ротацией и детектом повторного использования. А ещё ни один AI-эндпоинт не уезжает в прод без проверки почты — это гарантирует тест, который роняет CI.

---

## Почему не Bearer и не localStorage

Классическая SPA-схема — положить JWT в `localStorage` и слать `Authorization: Bearer`. Проблема одна, но большая: **любой XSS читает `localStorage` целиком**. Утёк токен — утекла сессия.

Мы пошли по cookie-пути:

- `access_token` и `refresh_token` — **httpOnly-куки**. JavaScript их не видит в принципе, `document.cookie` их не покажет. XSS не может их выгрести.
- Но куки сами по себе уязвимы к **CSRF**: браузер прикладывает их к любому запросу на наш домен, даже инициированному чужим сайтом.

Значит, нужен второй контур — защита от CSRF без серверного состояния. Это **double-submit**.

```text
   Браузер                                  Сервер (FastAPI)
   ───────                                  ────────────────
   access_token  (httpOnly)  ─── куки ───►  decode_token()
   refresh_token (httpOnly)                 │
   csrf_token   (НЕ httpOnly) ──┐           │  для POST/PUT/PATCH/DELETE:
                                │           ▼
   JS читает csrf_token  ───────┴─► заголовок X-CSRF-Token
                                              должен == csrf_token-куке,
                                              иначе 403
```

---

## Double-submit CSRF на проверке токена

Идея double-submit: значение CSRF лежит и в куке (не-httpOnly, JS её читает), и в заголовке. Атакующий сайт может *спровоцировать* запрос с нашими куками, но **не может прочитать** нашу куку, чтобы подставить правильный заголовок (мешает Same-Origin Policy). Сервер сверяет одно с другим:

```python
# backend/app/dependencies.py
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

async def get_current_token_payload(
    request: Request,
    access_token: str | None = Cookie(default=None),
    csrf_token: str | None = Cookie(default=None),
    redis: Redis = Depends(get_redis),
) -> dict:
    if not access_token:
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(access_token)
    ...
    if request.method in _STATE_CHANGING:
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_token or not csrf_header or csrf_header != csrf_token:
            raise HTTPException(403, "CSRF token invalid")
    return payload
```

Никакого серверного CSRF-стейта: всё стейтлесс, проверка — это одно сравнение строк. Пароли при этом хешируются Argon2id (а не bcrypt, что бы ни говорили старые куски доков):

```python
# backend/app/services/auth_service.py
from argon2 import PasswordHasher
_ph = PasswordHasher()

def hash_password(password: str) -> str:
    return _ph.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
```

---

## Refresh-токены: Redis-«семьи» и детект кражи

Access-токен живёт недолго. Когда он протухает, его обновляют по refresh-токену. Но refresh-токен — лакомый кусок: укради его — и можно бесконечно выписывать себе доступ. Поэтому мы делаем **ротацию с детектом повторного использования**.

Каждая сессия — это «семья» в Redis по ключу `refresh:{user_id}:{family_id}`, хранящая текущий `jti` (идентификатор актуального токена). При каждом обновлении выпускается новая пара, и `jti` семьи ротируется. Если приходит refresh-токен со **старым** `jti` — значит, кто-то переиспользовал уже ротированный токен. Это сигнатура кражи, и мы убиваем **всю семью**:

```python
# backend/app/services/auth_service.py
async def refresh(self, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Not a refresh token")
    user_id, family_id, token_jti = payload["sub"], payload["family_id"], payload["jti"]

    key = self._family_key(user_id, family_id)   # f"refresh:{user_id}:{family_id}"
    raw = await self.redis.get(key)
    if not raw:
        raise HTTPException(401, "Session expired")

    family = json.loads(raw)
    if family.get("jti") != token_jti:
        # Повторное использование ротированного jti — считаем кражей,
        # инвалидируем всю семью сессий.
        await self.redis.delete(key)
        raise HTTPException(401, "Token reuse detected. All sessions invalidated.")
    ...
    return await self._mint_pair(user=user, family_id=family_id, ...)
```

Получается дешёвый и сильный механизм: украденный и переигранный токен не просто отклоняется — он **обнуляет всю сессию**, заодно выкидывая и легитимного владельца, который тут же увидит, что его разлогинило.

---

## Singleflight-refresh на фронте: один `refresh` на пачку 401

Теперь фронт. Реактивная схема: словили 401 → обновили токен → повторили запрос. Но есть тонкость. Если страница разом стрельнула пятью запросами и access-токен только что протух, мы получим пять 401 почти одновременно. Запустить пять параллельных `refresh` нельзя: они ротируют токен по очереди, и часть из них прилетит со «старым» `jti` — и наш же детект кражи примет это за атаку и всех разлогинит.

Решение — **singleflight**: один общий `refreshPromise` на всю пачку.

```typescript
// frontend/src/composables/useApi.ts
let refreshPromise: Promise<boolean> | null = null

const tryRefresh = async (): Promise<boolean> => {
  if (!refreshPromise) {
    refreshPromise = $fetch('/auth/refresh', {
      baseURL: base, method: 'POST', credentials: 'include', headers: {},
    }).then(() => true).catch(() => false)
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise          // все ждут один и тот же запрос
}

// для state-changing и не /auth/* — прокидываем double-submit CSRF-заголовок
if (['POST','PUT','PATCH','DELETE'].includes(method) && !isAuthEndpoint(path)) {
  const csrf = getCsrfToken()    // читает не-httpOnly csrf_token-куку
  if (csrf) headers['X-CSRF-Token'] = csrf
}

// на 401: один refresh, потом ровно один повтор
if (is401 && !_isRetry && !isAuthEndpoint(path)) {
  const ok = await tryRefresh()
  if (ok) return apiFetch(path, options, true)     // retry once
}
if (is401 && !isAuthEndpoint(path) && !isSessionProbe(path)) {
  store.clearSession(); await navigateTo('/login')
}
```

Три детали, которые легко упустить:

- `/auth/refresh` зовётся с **пустыми заголовками** (`headers: {}`) — чтобы случайно не прокинуть устаревший `X-CSRF-Token`; новая csrf-кука перечитывается перед повтором.
- `/auth/me` — это **session probe**: 401 там не вызывает разлогин и редирект (`isSessionProbe`), поэтому публичные страницы могут спокойно «прощупать» авторизацию, не выбивая анонимного посетителя на `/login`.
- Повтор — **ровно один** (`_isRetry`), иначе на сломанной сессии можно уйти в цикл.

Это единственный путь обновления токена в приложении. Второй заводить нельзя — только расширять `useApi`.

---

## Черновики прячутся за 404, а не 403

Маленькая, но важная для приватности деталь. Если студент дёргает урок, который ещё не опубликован, мы отвечаем **404, а не 403**. 403 («запрещено») косвенно подтвердил бы, что ресурс существует. 404 не раскрывает вообще ничего:

```python
# backend/app/dependencies.py
if not visibility_service.lesson_visible_to_student(lesson.module, lesson):
    raise HTTPException(status_code=404, detail="Lesson not found")
return user, lesson, False
```

Видимость при этом не переколачивается инлайном — единственный источник истины про «опубликована ли вся цепочка курс→модуль→урок» — это `visibility_service`.

---

## AI-гейтинг, который роняет CI

Каждый вызов LLM/vision/TTS стоит денег и ресурсов, поэтому **любой такой эндпоинт обязан стоять за проверкой верифицированной почты** (`require_verified_email` / `require_verified_teacher`) и быть перечислен в реестре `AI_GATED_ENDPOINTS`. Мы не доверяем это бдительности ревьюера — мы доверяем тесту:

```python
# backend/tests/integration/test_ai_gating_guard.py
_VERIFIED_GATES = {require_verified_email, require_verified_teacher}

def test_registered_ai_endpoints_are_gated(app):
    for method, path in AI_GATED_ENDPOINTS:
        matches = [r for r in _api_routes(app) if r.path == path and method in _methods(r)]
        assert matches, f"{method} {path} перечислен, но такого роута нет"
        gates = set(_dependency_calls(matches[0].dependant)) & _VERIFIED_GATES
        assert gates, f"{method} {path} не имеет verified-email гейта"

def test_no_ungated_celery_ai_endpoint(app):
    for route in _api_routes(app):
        source = inspect.getsource(inspect.unwrap(route.endpoint))
        if ".apply_async(" not in source and ".delay(" not in source:
            continue
        if any(t in source for t in _INFRA_TASKS + _EXCLUDED_TASKS):
            continue
        for method in _methods(route):
            assert (method, route.path) in AI_GATED_ENDPOINTS
```

Тест двусторонний:

1. Каждый эндпоинт из реестра **реально существует** и **имеет** verified-email-гейт (зависимость ищется рекурсивным обходом дерева зависимостей роута).
2. Любой эндпоинт, чей исходник содержит `.apply_async(` или `.delay(`, **обязан** быть в реестре — кроме инфраструктурных (`send_email`) и осознанно исключённых (`grade_attempt_task`).

Добавил новый роут, который дёргает Celery-таск с AI, и забыл и про гейт, и про реестр — **сборка красная**. Студенческий грейдинг (`grade_attempt_task`) намеренно в белом списке исключений: он маркетингово бесплатный, и неверифицированного студента всё равно надо уметь оценить.

Сам реестр компактен — это `frozenset` из шести `(метод, путь)`: запуск анализа урока, генерация видео, регенерация слайда, генерация квиза, регенерация вопроса и AI-ревью.

---

## Грабли

- **Singleflight обязателен.** Без общего `refreshPromise` пачка 401 запускает параллельные ротации, и собственный детект кражи разлогинивает пользователя «на ровном месте».
- **`/auth/me` — не обычный эндпоинт.** Его 401 не должен выбивать на `/login`, иначе анонимы не смогут открыть публичные страницы.
- **`/auth/refresh` — с пустыми заголовками.** Иначе протухший `X-CSRF-Token` сломает обновление.
- **404, а не 403 на черновики.** 403 утечёт сам факт существования ресурса.
- **Два пути CSRF.** Полная авторизация (`get_current_token_payload`) и отдельная `check_csrf` для неаутентифицированных state-changing запросов — оба используют один `_STATE_CHANGING` и один и тот же 403.
- **Admin — это не роль, а секрет.** Админские эндпоинты биллинга гейтятся общим секретом в заголовке `X-Admin-Token`; пустой токен полностью выключает админку. Никакого `UserRole=admin` нет.

---

## Что выиграли

- **Ни один токен не попадает в JavaScript** — XSS не уносит сессию.
- **CSRF блокируется без серверного состояния** — одно сравнение строк.
- **Украденный refresh обнуляет всю семью сессий** — кража саморазоблачается.
- **Пользователь не видит ложных разлогинов** при протухшем access-токене — singleflight чинит это прозрачно.
- **Ни один AI-эндпоинт не уезжает в прод без гейта** — за этим следит CI, а не человек.

Главная мысль: безопасность здесь — не один «большой» механизм, а несколько маленьких границ, каждая из которых закрывает конкретный вектор (XSS → httpOnly, CSRF → double-submit, кража refresh → семьи с ротацией, человеческая забывчивость → guard-тест). И почти каждая граница продублирована правилом, которое нельзя обойти случайно.

→ Дальше в серии: **«Локальный AI вместо облака + биллинг по кредитам»** — что именно охраняют эти гейты и сколько это стоит.
