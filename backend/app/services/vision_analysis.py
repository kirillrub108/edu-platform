import asyncio
import base64
import hashlib
import structlog
import os
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = structlog.get_logger()


SUMMARY_CACHE_DIR = os.path.join(settings.STORAGE_PATH, "summaries_cache")
_SUMMARY_CONCURRENCY = 4


SLIDE_SUMMARY_SYSTEM_PROMPT = """\
Ты анализируешь слайд презентации. Цель — кратко описать его содержание,
чтобы другая LLM могла правильно сопоставить слайд с фрагментом текста доклада.

Дай 2–4 коротких предложения о:
1. Заголовке/теме слайда (если есть).
2. Ключевых тезисах, понятиях или терминах с этого слайда.
3. Визуальных элементах, если они несут смысл (схема, график, диаграмма,
   иллюстрация) — кратко опиши, что они показывают.

ПРАВИЛА:
- НЕ пересказывай буллеты дословно — обобщай.
- НЕ описывай дизайн, фон, цветовую гамму.
- НЕ начинай со слов "На слайде..." — пиши сразу по сути.
- Длина: 30–80 слов.
- Только сам текст саммари, без префиксов и заголовков.

Язык: русский.
"""


SLIDE_SUMMARY_USER_TEMPLATE = """\
Слайд {slide_number} из {total_slides}.
Опиши его содержание кратко.
"""


VISION_SYSTEM_PROMPT = """\
Ты — опытный преподаватель-методист, создающий профессиональный учебный контент.
Твоя задача: по изображению слайда написать текст озвучки для видеолекции.

ТРЕБОВАНИЯ К ТЕКСТУ:
1. ГЛУБИНА И ПОЛНОТА: Полностью раскрой тему слайда. Не пересказывай буллеты — объясняй суть.
   Если на слайде написано «Преимущества микросервисов» — объясни ПОЧЕМУ они преимущества,
   приведи конкретные примеры из практики, расскажи о контексте применения.

2. СТРУКТУРА ОБЪЯСНЕНИЯ:
   - Сначала — суть (что это и зачем)
   - Потом — механизм (как это работает)
   - Затем — применение (где и когда это нужно)
   - Если уместно — сравнение с альтернативами

3. ЯЗЫК: Разговорный, но профессиональный. Как объясняет хороший преподаватель студентам.
   Избегай сухого перечисления! Используй связки, примеры, аналогии.

4. ДЛИНА: 150–300 слов на слайд. Не меньше — текст должен быть развёрнутым.
   Исключение — титульные слайды и слайды-разделители (50–80 слов).

5. АНАЛИЗ ИЗОБРАЖЕНИЯ: Внимательно изучи всё что есть на слайде:
   - Текстовые блоки, заголовки, буллеты
   - Схемы, диаграммы, стрелки, связи между объектами
   - Иконки, иллюстрации (описывай что они означают в контексте)
   - Таблицы, графики (интерпретируй данные)

6. КОНТЕКСТ КУРСА: Учитывай название курса и позицию слайда.
   Обеспечивай логический переход от предыдущих тем.

7. ТОЛЬКО ТЕКСТ ОЗВУЧКИ: Не добавляй метаданные, заголовки, нумерацию.
   Выведи только сам текст, который будет озвучен.

Язык вывода: русский (если на слайде не указан другой язык явно).
"""


SLIDE_USER_PROMPT_TEMPLATE = """\
Курс: {course_title}
Слайд {slide_number} из {total_slides}
{context_section}

Напиши текст озвучки для этого слайда.
"""


def _encode_image(image_path: str, max_dim: int = 1280) -> str:
    """Resize image to max_dim on the longest side, convert to JPEG, return base64."""
    import io as _io

    from PIL import Image

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


def _build_user_content(
    image_path: str,
    course_title: str,
    slide_number: int,
    total_slides: int,
    previous_context: str,
) -> list[dict[str, Any]]:
    context_section = ""
    if previous_context:
        context_section = f"Контекст предыдущих слайдов:\n{previous_context}"

    user_text = SLIDE_USER_PROMPT_TEMPLATE.format(
        course_title=course_title,
        slide_number=slide_number,
        total_slides=total_slides,
        context_section=context_section,
    )
    image_b64 = _encode_image(image_path)
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        },
        {"type": "text", "text": user_text},
    ]


def _summarise_for_context(text: str, max_chars: int = 280) -> str:
    """Cheap one-line summary used as accumulated context for next slides."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


class VisionAnalysisService:
    """Generate per-slide narration from rendered PNG images via a vision LLM."""

    def __init__(self) -> None:
        self.provider = (settings.VISION_PROVIDER or "ollama").lower()
        if self.provider == "ollama":
            self._ollama_client = AsyncOpenAI(
                base_url=settings.VISION_OLLAMA_BASE_URL,
                api_key=settings.VISION_API_KEY,
            )
            self._model = settings.VISION_MODEL
        elif self.provider == "yandex":
            self._ollama_client = None
            self._model = settings.YANDEX_VISION_MODEL
        else:
            raise ValueError(f"Unknown VISION_PROVIDER: {self.provider!r}")

    async def analyze_slide(
        self,
        slide_image_path: str,
        slide_number: int,
        total_slides: int,
        course_title: str,
        previous_context: str = "",
    ) -> str:
        """Return narration text for one slide."""
        user_content = _build_user_content(
            slide_image_path,
            course_title,
            slide_number,
            total_slides,
            previous_context,
        )

        if self.provider == "ollama":
            return await self._call_ollama(user_content)
        return await self._call_yandex(user_content)

    async def analyze_presentation(
        self,
        slide_image_paths: list[str],
        course_title: str,
        progress_cb: Any = None,
    ) -> list[str]:
        """Analyse all slides sequentially with accumulated context."""
        results: list[str] = []
        context_lines: list[str] = []
        total = len(slide_image_paths)

        for idx, path in enumerate(slide_image_paths):
            slide_number = idx + 1
            previous_context = "\n".join(context_lines[-3:])  # last 3 slides only
            try:
                text = await self.analyze_slide(
                    slide_image_path=path,
                    slide_number=slide_number,
                    total_slides=total,
                    course_title=course_title,
                    previous_context=previous_context,
                )
            except Exception:
                logger.exception("vision_analysis_failed", slide=slide_number)
                text = ""

            results.append(text)
            if text:
                context_lines.append(f"Слайд {slide_number}: {_summarise_for_context(text)}")

            if progress_cb is not None:
                try:
                    progress_cb(slide_number, total)
                except Exception:
                    logger.exception("progress_cb_error")

        return results

    async def summarize_slide(
        self,
        slide_image_path: str,
        slide_number: int,
        total_slides: int,
    ) -> str:
        """Return a short content summary (2–4 sentences) for one slide.

        Used as alignment hint when splitting a long lecture script into
        per-slide chunks. Independent of other slides — no accumulated
        context, so calls can be parallelised safely.
        """
        image_b64 = _encode_image(slide_image_path)
        user_text = SLIDE_SUMMARY_USER_TEMPLATE.format(
            slide_number=slide_number, total_slides=total_slides
        )
        user_content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
            },
            {"type": "text", "text": user_text},
        ]
        if self.provider == "ollama":
            return await self._call_ollama(user_content, system=SLIDE_SUMMARY_SYSTEM_PROMPT)
        return await self._call_yandex(user_content, system=SLIDE_SUMMARY_SYSTEM_PROMPT)

    async def summarize_presentation(
        self,
        slide_image_paths: list[str],
        progress_cb: Any = None,
    ) -> list[str]:
        """Summarise every slide in parallel, with on-disk cache by PNG hash.

        Cached results are keyed by sha256 of the image bytes + provider/model
        (so changing the model invalidates the cache). progress_cb is called
        as (done, total) after each slide is finalised.
        """
        os.makedirs(SUMMARY_CACHE_DIR, exist_ok=True)
        total = len(slide_image_paths)

        cache_keys = [self._cache_key(p) for p in slide_image_paths]
        results: list[str] = ["" for _ in slide_image_paths]
        pending: list[int] = []

        for idx, key in enumerate(cache_keys):
            cached = self._read_cache(key)
            if cached is not None:
                results[idx] = cached
            else:
                pending.append(idx)

        done = total - len(pending)
        if progress_cb is not None and done > 0:
            try:
                progress_cb(done, total)
            except Exception:
                logger.exception("progress_cb raised")

        if not pending:
            return results

        sem = asyncio.Semaphore(_SUMMARY_CONCURRENCY)
        progress_lock = asyncio.Lock()

        async def _one(idx: int) -> None:
            nonlocal done
            async with sem:
                try:
                    text = await self.summarize_slide(
                        slide_image_path=slide_image_paths[idx],
                        slide_number=idx + 1,
                        total_slides=total,
                    )
                except Exception:
                    logger.exception("slide_summary_failed", slide=idx + 1)
                    text = ""
            results[idx] = text
            if text:
                self._write_cache(cache_keys[idx], text)
            async with progress_lock:
                done += 1
                if progress_cb is not None:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        logger.exception("progress_cb_error")

        await asyncio.gather(*(_one(i) for i in pending))
        return results

    def _cache_key(self, image_path: str) -> str:
        """Stable cache key: sha256(file bytes) + provider/model identifier."""
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            for block in iter(lambda: f.read(64 * 1024), b""):
                h.update(block)
        h.update(b"|")
        h.update(self.provider.encode())
        h.update(b"|")
        h.update((self._model or "").encode())
        return h.hexdigest()

    def _read_cache(self, key: str) -> str | None:
        path = os.path.join(SUMMARY_CACHE_DIR, f"{key}.txt")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("summary_cache_read_failed", path=str(path))
            return None

    def _write_cache(self, key: str, text: str) -> None:
        path = os.path.join(SUMMARY_CACHE_DIR, f"{key}.txt")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception:
            logger.exception("summary_cache_write_failed", path=str(path))
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def _call_ollama(
        self,
        user_content: list[dict[str, Any]],
        system: str = VISION_SYSTEM_PROMPT,
    ) -> str:
        assert self._ollama_client is not None
        resp = await self._ollama_client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        return (resp.choices[0].message.content or "").strip()

    async def _call_yandex(
        self,
        user_content: list[dict[str, Any]],
        system: str = VISION_SYSTEM_PROMPT,
    ) -> str:
        """YandexGPT Pro Foundation Models API call.

        Uses the OpenAI-compatible v1/chat/completions endpoint exposed by
        Yandex Foundation Models. The vision payload follows the same content
        array format (image_url + text) as OpenAI Vision.
        """
        if not settings.YANDEX_API_KEY or not settings.YANDEX_FOLDER_ID:
            raise RuntimeError(
                "YANDEX_API_KEY and YANDEX_FOLDER_ID must be set for vision provider 'yandex'"
            )

        url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
        model_uri = f"gpt://{settings.YANDEX_FOLDER_ID}/{self._model}/latest"
        headers = {
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_uri,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            logger.error("yandex_gpt_unexpected_response", data=data)
            return ""


vision_analysis_service = VisionAnalysisService()
