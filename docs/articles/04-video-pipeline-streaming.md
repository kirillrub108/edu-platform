# Как мы почти вдвое ускорили сборку видеоурока: стриминг TTS→FFmpeg через `as_completed`

> **Площадка:** Habr · **Хабы:** Python, Многопоточность, FFmpeg, Backend, Производительность · **Время чтения:** ~10 мин

**TL;DR.** Сборка озвученного видеоурока — это N слайдов, каждому нужна сначала озвучка (TTS), потом кодирование (FFmpeg). Наивный путь «озвучить всё → закодировать всё» оставляет кодировщик простаивать всё время TTS. Мы запустили два пула потоков и соединили их через `concurrent.futures.as_completed`: как только готов WAV слайда k, он немедленно уходит на кодирование. Перекрытие срезает латентность сборки примерно вдвое. Разбираем код, тюнинг и грабли (включая рендер слайдов через LibreOffice).

---

## Анатомия задачи

На входе — PPTX и сценарий лекции. На выходе — MP4, где каждый слайд показывается ровно столько, сколько звучит его озвучка. Конвейер по слайду:

```text
для каждого слайда i:
   текст сценария ──► TTS (HTTP к Silero) ──► WAV
   PNG слайда   ─┐
   WAV          ─┴─► FFmpeg (encode_segment) ──► .mkv-сегмент
все сегменты ──► concat ──► final.mp4
```

Две стадии принципиально разной природы:

- **TTS** — I/O-bound. Это HTTP-запрос к сервису синтеза; поток в основном ждёт сеть.
- **Кодирование** — CPU/process-bound. На каждый слайд поднимается отдельный процесс FFmpeg.

Если делать «в лоб» — сначала всю озвучку, потом всё кодирование — кодировщик (самый дорогой ресурс) простаивает всю первую фазу.

```text
Последовательно (TTS-всё → encode-всё):
TTS:  [s0][s1][s2][s3]
ENC:                  [s0][s1][s2][s3]
                      └── FFmpeg простаивал всю фазу TTS ──┘

Стримингом (as_completed):
TTS:  [s0][s1][s2][s3]
ENC:      [s0][s1][s2][s3]
          └── encode s0 стартует, как только готов его WAV ──┘
```

---

## Решение: два пула, соединённые `as_completed`

Сердце пайплайна — два `ThreadPoolExecutor`, открытых в одном `with`, и `as_completed`, который превращает «готовый WAV» в «немедленный старт кодирования».

```python
# backend/app/tasks/video_pipeline.py
with (
    ThreadPoolExecutor(max_workers=_TTS_WORKERS, thread_name_prefix="tts") as tts_pool,
    ThreadPoolExecutor(max_workers=_ENCODE_WORKERS, thread_name_prefix="enc") as enc_pool,
):
    slides_needing_tts = [i for i in range(total_slides) if i not in cp_segments_done]
    tts_futures = {tts_pool.submit(_do_tts, i): i for i in slides_needing_tts}
    enc_futures: dict = {}

    # Чейнинг: каждый завершённый TTS немедленно порождает задачу кодирования.
    for tts_future in as_completed(tts_futures):
        idx, audio_path = tts_future.result()
        enc_future = enc_pool.submit(
            video_service.encode_segment,
            idx, image_paths[idx], audio_path, seg_work_dir,
        )
        enc_futures[enc_future] = idx
        _checkpoint("tts", ...)

    # Сбор результатов кодирования (enc_pool ещё жив внутри того же `with`).
    for enc_future in as_completed(enc_futures):
        idx = enc_futures[enc_future]
        segment_paths[idx] = enc_future.result()
        _checkpoint("encoding", ...)
```

Ключ здесь — что оба `for ... as_completed` стоят **внутри одного `with`**. Пока первый цикл сабмитит задачи кодирования по мере готовности WAV-ов, `enc_pool` уже их выполняет. Слайд `0` кодируется, пока озвучиваются `1…4`. Это прямо зафиксировано в комментарии у кода — чтобы при рефакторинге никто случайно не вернул «сначала всё TTS»:

```python
# Два отдельных пула потоков работают параллельно:
#   tts_pool  (4 воркера) — один HTTP-запрос к Silero на поток
#   enc_pool  (3 воркера) — один процесс FFmpeg на поток
#
# Как только резолвится TTS-future, его задача кодирования
# сабмитится немедленно. То есть кодирование слайда N
# перекрывается с озвучкой слайдов N+1 … N+4, вместо того
# чтобы ждать завершения всего TTS.
```

Почему два *разных* пула, а не один общий? Потому что стадии упираются в разные ресурсы. TTS-поток ждёт сеть — их можно держать побольше. Кодирование жрёт CPU — их должно быть меньше, чтобы не задушить машину. Раздельные пулы → раздельный, независимо настраиваемый параллелизм.

---

## Тюнинг живёт в одном месте

Размеры пулов и прочие ручки не разбросаны по коду — они в `constants.py`:

```python
# backend/app/constants.py
TTS_WORKERS    = 4    # совпадает с NUMBER_OF_THREADS контейнера silero-tts
ENCODE_WORKERS = 3    # параллельные процессы FFmpeg; оставляет запас под LO и TTS
SILERO_MAX_CHARS = 800   # консервативный лимит: Silero отдаёт 500 на очень длинном входе
SLIDE_DPI = 150          # на 1080p неотличимо от 300 DPI, но PNG в ~4 раза меньше
MAX_SCRIPT_BYTES = 10 * 1024 * 1024   # 10 МБ
```

`TTS_WORKERS=4` не случайно: это ровно число потоков, которое умеет наш Silero-контейнер. А размер TTS-пула ещё и зависит от провайдера — у облачного шлюза другие лимиты:

```python
_TTS_WORKERS = (
    settings.POLZA_TTS_WORKERS if settings.TTS_PROVIDER == "polza" else TTS_WORKERS
)
_ENCODE_WORKERS = ENCODE_WORKERS
```

Сама озвучка спрятана за единым интерфейсом — пайплайну всё равно, какой провайдер:

```python
# backend/app/services/tts_service.py
def synthesize(self, text, output_path, voice=None) -> str:
    provider = settings.TTS_PROVIDER
    effective_voice = voice or settings.SILERO_TTS_VOICE
    if provider == "silero":
        return self._synthesize_silero(text, output_path, effective_voice)
    elif provider == "polza":
        return self._synthesize_polza(text, output_path, effective_voice)
    elif provider == "yandex":
        raise NotImplementedError("Yandex SpeechKit TTS is not configured yet")
    else:
        return self._synthesize_stub(text, output_path)
```

---

## Откуда берутся PNG слайдов

Перед озвучкой PPTX надо превратить в картинки. Отдельного «рендерера» у нас нет — мы шеллим из headless LibreOffice (PPTX→PDF), потом `pdftoppm` (PDF→PNG):

```python
# backend/app/services/video_service.py
_run([
    "libreoffice", "--headless",
    f"-env:UserInstallation=file://{lo_user_dir}",
    "--convert-to", "pdf", "--outdir", pdf_dir, pptx_path,
])
_run([
    "pdftoppm", "-png", "-r", str(SLIDE_DPI),
    "-aa", "yes", "-aaVector", "yes",
    pdf_path, os.path.join(output_dir, "slide"),
])
```

Рендер дорогой, поэтому PNG кэшируются на диск по **хешу содержимого** PPTX. Ключ кэша — md5 байтов файла плюс DPI, так что смена `SLIDE_DPI` автоматически инвалидирует старый кэш:

```python
def _pptx_cache_key(pptx_path: str) -> str:
    """Хеш содержимого + DPI → стабильный ключ для кэша PNG-слайдов."""
    h = hashlib.md5()
    with open(pptx_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"{h.hexdigest()}_dpi{SLIDE_DPI}"
```

Перегенерил тот же урок — слайды берутся из кэша, LibreOffice не запускается вовсе.

---

## Устойчивость к падениям: per-slide checkpoints

Минутная задача может упасть на середине — воркер перезапустили, провайдер ответил ошибкой. Мы не хотим переозвучивать 39 готовых слайдов из-за 40-го. Поэтому по ходу пайплайн пишет per-slide чекпоинты в Redis (`tts_done`, `segments_done`): слайд, у которого уже есть готовый `.mkv`-сегмент, при повторном прогоне **пропускает TTS целиком**. В коде это видно по `slides_needing_tts = [i for i in range(total_slides) if i not in cp_segments_done]`.

А при отмене генерации оба пула гасятся «жёстко» — `shutdown(wait=False, cancel_futures=True)`: то, что в очереди, выбрасывается; то, что уже в работе, доигрывает.

---

## Грабли, на которых постояли

- **Нельзя возвращаться к «TTS-всё → encode-всё».** И комментарий в коде, и заметка в `CLAUDE.md` прямо предупреждают: это примерно удваивает латентность пайплайна. Стриминговую связь надо беречь при любом рефакторинге.
- **Потоки пула не трогают главную сессию задачи.** `_do_tts` открывает собственную `with SyncSession()` на поток, а контекст для биллинга/метрик переустанавливается в каждом потоке заново — `ContextVar` не переходят через границу потока.
- **PDF в LibreOffice не гоняем.** Если на вход пришёл уже PDF — он идёт прямо в `pdftoppm`, минуя LibreOffice (тот корёжит встроенные шрифты, особенно кириллицу). Для PDF кэш слайдов тоже пропускается.
- **Silero капризен к смешанным глифам.** На смеси CJK и кириллицы он отвечает «Invalid XML format» → HTTP 500. А облачный Polza отдаёт mp3, который мы транскодируем в 48 кГц mono WAV — чтобы совпасть с частотой Silero и не заставлять FFmpeg ресемплить.
- **Сегменты — `.mkv`, не `.mp4` на слайд.** `encode_segment` возвращает `.mkv`-интермедиаты, которые потом конкатятся в финальный `.mp4`.
- **Кэши растут без сборки мусора.** `slides_cache/` и `tts_cache/` ключуются по хешу и безопасны к удалению, но автоматически не чистятся.

---

## Что выиграли

- **Латентность сборки ~вдвое ниже** против последовательной схемы: кодирование прячется за временем озвучки.
- **Раздельный параллелизм** под I/O-bound TTS и CPU-bound FFmpeg — каждый пул настраивается своим числом воркеров.
- **Дешёвые перезапуски**: чекпоинты дают resume без переозвучки готовых слайдов.
- **Бесплатные перегенерации**: кэш слайдов по хешу содержимого экономит самый дорогой шаг — LibreOffice.

Мораль: когда у вас конвейер из стадий разной природы, не выстраивайте их «стенка к стенке». `as_completed` — копеечный по коду способ заставить дорогую стадию начинаться ровно в тот момент, когда готов первый вход, а не когда закончится вся предыдущая фаза.

→ Дальше в серии: **«Auth без Bearer и localStorage»** — как защищён эндпоинт, который всё это запускает.
