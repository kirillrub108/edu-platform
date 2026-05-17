import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

LECTURE_ENHANCEMENT_PROMPT = """\
Ты — методист и редактор образовательного контента.
Получаешь черновик текста доклада и делаешь из него профессиональный текст лекции.

ЗАДАЧА:
Переработай или дополни черновой текст так, чтобы он:

1. ПОЛНОСТЬЮ РАСКРЫВАЛ ТЕМУ: Каждый тезис объясни с нуля, не предполагая знаний у слушателя.
   Добавь контекст: зачем это нужно, как появилось, какую проблему решает.

2. БЫЛ САМОДОСТАТОЧНЫМ: Слушатель должен понять тему только из этого текста,
   без дополнительного чтения. Никаких «как вы знаете» или «очевидно, что».

3. ИМЕЛ СТРУКТУРУ ОБЪЯСНЕНИЯ для каждого ключевого понятия:
   → Что это (определение простыми словами)
   → Зачем нужно (проблема которую решает)
   → Как работает (механизм, алгоритм, логика)
   → Где применяется (конкретные примеры)
   → Что важно знать (нюансы, подводные камни)

4. ИСПОЛЬЗОВАЛ АНАЛОГИИ И ПРИМЕРЫ: Минимум 1-2 конкретных примера или аналогии
   из реальной практики на каждый ключевой тезис.

5. БЫЛ СВЯЗНЫМ ТЕКСТОМ: Не список буллетов, а связное повествование с логическими переходами.

ФОРМАТ ВЫВОДА: Только готовый текст озвучки. Без метаданных.
Объём: в 1.5–2 раза больше исходного черновика, но не короче 200 слов.
"""


_SSML_SYSTEM = """\
You are a strict text formatter for an audio narration system. You DO NOT rewrite or paraphrase content. You DO NOT add new sentences or remove informational sentences.

Your only allowed operations:

A) Split the lecture script into exactly N consecutive chunks (one per slide), preserving the original word order and wording.
   - Use slide_texts (visible text from each slide) as alignment anchors. Each chunk N must correspond to slide N — start chunk N where the script begins discussing the content shown on slide N.
   - If the script does not explicitly map, use semantic alignment with the slide's visible text.

B) Cleanup — only remove these meta-tokens that should not be spoken:
   - Slide labels: "Слайд 1", "Slide 1:", "Слайд №2 —", standalone numerical headers like "1." at the start of lines.
   - Bullet glyphs at line start: •, *, ‣, –, —, -.
   - Editor notes in parentheses or brackets that clearly are NOT spoken content: (пауза), (слайд 3), [см. слайд], (note).
   - DO NOT remove any actual words of the lecture, even if they look redundant.

C) Number-to-words conversion — replace all digits and numeric expressions with their spoken Russian equivalents, choosing the grammatically correct form based on context:
   - Cardinal/genitive by context: "до 7 метров" → "до семи метров", "100 человек" → "ста человек".
   - Years: "в 2024 году" → "в две тысячи двадцать четвёртом году".
   - Percentages: "35%" → "тридцать пять процентов".
   - Ordinals: "3-й этап" → "третий этап", "1-е место" → "первое место".
   - Ranges: "5–10 лет" → "от пяти до десяти лет".
   - Decimals: "3.5 кг" → "три с половиной килограмма".
   - Large numbers: "1 000 000" → "один миллион".
   Apply to ALL digits in the output — no digit characters should remain in the final chunks.

D) SSML annotation — wrap the cleaned text with semantic markup. DO NOT wrap in <speak> (the system adds that). Allowed tags only:
   - <p>...</p> around each paragraph / coherent thought.
   - <break time="500ms"/> between distinct points within a paragraph.
   - <break time="800ms"/> between major topic shifts.
   - <prosody rate="slow">term</prosody> ONLY around defined technical terms when they first appear.
   Do NOT add prosody pitch, do NOT add <s>, do NOT add anything else.

Output format — strictly a JSON object:
{"chunks": ["<p>...</p>", "<p>...</p>"]}
with exactly N string items.
"""


class LLMService:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )
        self.model = settings.LLM_MODEL

    @staticmethod
    def _strip_think(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    async def _chat(
        self, system: str, user: str, json_mode: bool = False, think: bool = False
    ) -> str:  # noqa: E501
        if not think:
            user = user + "\n/no_think"
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        return self._strip_think(response.choices[0].message.content or "")

    async def split_and_annotate_ssml(
        self,
        script: str,
        slides_count: int,
        slide_texts: list[str] | None = None,
    ) -> tuple[list[str], str | None]:
        """Split script into N chunks aligned with slides, with SSML annotation.

        Returns (chunks, warning) where warning is non-None when the LLM returned
        the wrong number of chunks and fallback splitting was used.
        """
        anchors = ""
        if slide_texts:
            anchor_lines = []
            for i, t in enumerate(slide_texts):
                snippet = (t or "").strip().replace("\n", " ")[:300]
                anchor_lines.append(f"Slide {i + 1}: {snippet}")
            anchors = (
                "Slide visible texts (alignment anchors):\n" + "\n".join(anchor_lines) + "\n\n"
            )  # noqa: E501

        user = (
            f"Slides count: {slides_count}\n\n"
            f"{anchors}"
            f"Lecture script (preserve wording verbatim):\n{script}"
        )
        raw = await self._chat(_SSML_SYSTEM, user, json_mode=True)
        try:
            data = json.loads(raw)
            chunks = data.get("chunks", [])
            if len(chunks) == slides_count and all(chunks):
                return [str(c) for c in chunks], None
            got = len(chunks)
            logger.warning("LLM returned %d SSML chunks for %d slides", got, slides_count)
            warning = (
                f"LLM вернул {got} чанков вместо {slides_count}. "
                "Использован fallback — качество озвучки может быть ниже."
            )
            return self._fallback_ssml(script, slides_count), warning
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM SSML JSON: %s", raw[:300])
        return self._fallback_ssml(script, slides_count), None

    def _fallback_ssml(self, text: str, n: int) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        chunk_size = max(1, len(sentences) // n)
        chunks: list[str] = []
        for i in range(n):
            start = i * chunk_size
            end = start + chunk_size if i < n - 1 else len(sentences)
            chunk = " ".join(sentences[start:end]).strip()
            ssml = f"<p>{chunk or f'Слайд {i + 1}'}</p>"
            chunks.append(ssml)
        return chunks

    async def generate_script_from_slide(self, slide_text: str) -> str:
        system = (
            "You are a lecturer. Rewrite the slide notes as a natural, spoken script "
            "(~80-150 words), suitable for narration."
        )
        return await self._chat(system, slide_text)

    async def enhance_lecture_text(
        self,
        draft: str,
        course_title: str = "",
    ) -> str:
        """Take a draft lecture text and produce a deeper, self-contained narration.

        Used in the "presentation_and_text" mode when the teacher uploads a
        rough script that should be expanded for the audience.
        """
        system = LECTURE_ENHANCEMENT_PROMPT
        user = (f"Курс: {course_title}\n\n" if course_title else "") + f"Черновик доклада:\n{draft}"
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
        response = await self.client.chat.completions.create(**kwargs)
        return self._strip_think(response.choices[0].message.content or "")

    async def generate_quiz(
        self, lesson_text: str, questions_count: int = 5
    ) -> list[dict[str, Any]]:
        system = (
            "Generate a multiple-choice quiz from the lesson. "
            'Output JSON: {"questions": [{"question": "...", "options": ["a","b","c","d"], '
            '"correct_index": 0}, ...]}'
        )
        user = f"Questions count: {questions_count}\n\nLesson:\n{lesson_text}"

        raw = await self._chat(system, user, json_mode=True, think=True)
        try:
            data = json.loads(raw)
            return data.get("questions", [])
        except json.JSONDecodeError:
            logger.error("Failed to parse quiz JSON: %s", raw)
            return []


llm_service = LLMService()
