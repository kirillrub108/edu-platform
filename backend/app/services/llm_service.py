import json
import logging
import re
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.config import settings
from app.constants import QUIZ_LLM_TEMPERATURE
from app.schemas.quiz import FlagKind, GeneratedQuestion, QuestionFlag, RegenerateMode

logger = logging.getLogger(__name__)


class LLMOutputError(RuntimeError):
    """Raised when the LLM returns malformed output after the retry budget."""

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
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        think: bool = False,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> str:
        if not think:
            user = user + "\n/no_think"
        kwargs: dict[str, Any] = {
            "model": model if model is not None else self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        return self._strip_think(response.choices[0].message.content or "")

    async def _chat_json_validated[T](
        self,
        system: str,
        user: str,
        validator: Callable[[dict[str, Any]], T],
        *,
        temperature: float = 0.1,
        purpose: str = "llm",
    ) -> T:
        """Call the LLM in JSON mode, parse, validate; retry once on malformed
        output. Raises LLMOutputError if both attempts fail validation.

        The validator returns the typed payload or raises ValueError for shape
        problems — the retry only triggers on JSONDecodeError or ValueError.
        """
        last_error: str | None = None
        for attempt in range(2):
            raw = await self._chat(system, user, json_mode=True, temperature=temperature)
            try:
                data = json.loads(raw)
                return validator(data)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "%s: malformed LLM output (attempt %d/2): %s; raw=%s",
                    purpose,
                    attempt + 1,
                    exc,
                    raw[:300],
                )
        raise LLMOutputError(f"{purpose}: LLM returned invalid output: {last_error}")

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
        # Single slide — nothing to split, annotate the whole script directly.
        if slides_count == 1:
            return [await self._annotate_ssml(script)], None

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
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM SSML JSON: %s", raw[:300])
            warning = None

        # Mechanical split, then annotate each chunk so SSML markup is preserved.
        raw_chunks = self._split_sentences(script, slides_count)
        annotated = [await self._annotate_ssml(c) for c in raw_chunks]
        return annotated, warning

    async def _annotate_ssml(self, text: str) -> str:
        """Apply the same cleanup + number-to-words + SSML rules as the main
        split-and-annotate pipeline, but for a single pre-split chunk."""
        if not text.strip():
            return "<p></p>"
        _ANNOTATE_SYSTEM = """\
You are a strict text formatter for an audio narration system. You DO NOT rewrite or paraphrase content. You DO NOT add new sentences or remove informational sentences.

Apply the following operations to the input text:

A) Cleanup — only remove these meta-tokens that should not be spoken:
   - Slide labels: "Слайд 1", "Slide 1:", "Слайд №2 —", standalone numerical headers like "1." at the start of lines.
   - Bullet glyphs at line start: •, *, ‣, –, —, -.
   - Editor notes in parentheses or brackets that clearly are NOT spoken content: (пауза), (слайд 3), [см. слайд], (note).
   - DO NOT remove any actual words of the lecture, even if they look redundant.

B) Number-to-words conversion — replace all digits and numeric expressions with their spoken Russian equivalents, choosing the grammatically correct form based on context:
   - Cardinal/genitive by context: "до 7 метров" → "до семи метров", "100 человек" → "ста человек".
   - Years: "в 2024 году" → "в две тысячи двадцать четвёртом году".
   - Percentages: "35%" → "тридцать пять процентов".
   - Ordinals: "3-й этап" → "третий этап", "1-е место" → "первое место".
   - Ranges: "5–10 лет" → "от пяти до десяти лет".
   - Decimals: "3.5 кг" → "три с половиной килограмма".
   - Large numbers: "1 000 000" → "один миллион".
   Apply to ALL digits in the output — no digit characters should remain.

C) SSML annotation — wrap the cleaned text with semantic markup. DO NOT wrap in <speak>. Allowed tags only:
   - <p>...</p> around each paragraph / coherent thought.
   - <break time="500ms"/> between distinct points within a paragraph.
   - <break time="800ms"/> between major topic shifts.
   - <prosody rate="slow">term</prosody> ONLY around defined technical terms when they first appear.
   Do NOT add prosody pitch, do NOT add <s>, do NOT add anything else.

Output ONLY the annotated text — no JSON, no explanations, no wrapper tags."""
        result = await self._chat(_ANNOTATE_SYSTEM, text)
        return result.strip() if result.strip() else f"<p>{text}</p>"

    def _split_sentences(self, text: str, n: int) -> list[str]:
        """Mechanically split text into N parts by sentences."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        chunk_size = max(1, len(sentences) // n)
        chunks: list[str] = []
        for i in range(n):
            start = i * chunk_size
            end = start + chunk_size if i < n - 1 else len(sentences)
            chunk = " ".join(sentences[start:end]).strip()
            chunks.append(chunk or f"Слайд {i + 1}")
        return chunks

    def _fallback_ssml(self, text: str, n: int) -> list[str]:
        return [f"<p>{c}</p>" for c in self._split_sentences(text, n)]

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

    async def refine_slide_narration(self, vision_text: str, model: str) -> str:
        """Polish the raw vision-model output into clean narration.

        Called after analyze_slide() because regenerate uses a vision-only path
        (no separate text LLM phase). This step cleans up any vision artifacts
        and ensures the text reads as natural spoken narration.
        """
        system = (
            "Ты — редактор текста озвучки учебной видеолекции.\n"
            "Получаешь текст, сгенерированный моделью анализа изображений.\n"
            "Задача: убрать артефакты (незавершённые фразы, описания дизайна, "
            "технические метки), исправить стиль — текст должен звучать как "
            "живая речь преподавателя. Не добавляй новую информацию, не сокращай смысл.\n"
            "Выведи только готовый текст без комментариев."
        )
        logger.debug("refine_slide_narration: using model=%s", model)
        return await self._chat(system, vision_text, model=model)

    async def generate_quiz(
        self,
        material: str,
        *,
        num_questions: int,
        num_options: int,
    ) -> list[GeneratedQuestion]:
        """Generate a multiple-choice quiz strictly grounded in `material`.

        Returns validated questions. Raises LLMOutputError if the LLM refuses
        to produce well-formed output after one retry.
        """
        system = _QUIZ_GENERATE_SYSTEM
        user = (
            f"Кол-во вопросов: {num_questions}\n"
            f"Кол-во вариантов на вопрос: {num_options}\n\n"
            f"Материал:\n{material}"
        )

        def _validate(data: dict[str, Any]) -> list[GeneratedQuestion]:
            raw_questions = data.get("questions")
            if not isinstance(raw_questions, list) or not raw_questions:
                raise ValueError("missing or empty 'questions' array")
            if len(raw_questions) != num_questions:
                raise ValueError(
                    f"expected {num_questions} questions, got {len(raw_questions)}"
                )
            return [_parse_question(item, num_options) for item in raw_questions]

        return await self._chat_json_validated(
            system,
            user,
            _validate,
            temperature=QUIZ_LLM_TEMPERATURE,
            purpose="generate_quiz",
        )

    async def regenerate_quiz_question(
        self,
        material: str,
        question: GeneratedQuestion,
        mode: RegenerateMode,
        num_options: int,
    ) -> GeneratedQuestion:
        """Apply a single-question transformation. For `improve_distractors`
        the correct option text must remain identical — enforced as a
        retry-triggering validation error so the user never gets a silently
        mutated answer.
        """
        system = _QUIZ_REGENERATE_SYSTEM_BASE + "\n\n" + _REGENERATE_MODE_RULES[mode]
        current = {
            "question": question.question,
            "options": list(question.options),
            "correct_index": question.correct_index,
        }
        user = (
            f"Кол-во вариантов: {num_options}\n\n"
            f"Материал:\n{material}\n\n"
            f"Текущий вопрос (JSON):\n{json.dumps(current, ensure_ascii=False)}"
        )

        expected_correct = question.options[question.correct_index].strip().lower()

        def _validate(data: dict[str, Any]) -> GeneratedQuestion:
            parsed = _parse_question(data, num_options)
            if mode == "improve_distractors":
                got = parsed.options[parsed.correct_index].strip().lower()
                if got != expected_correct:
                    raise ValueError(
                        "improve_distractors must preserve the correct option text"
                    )
            return parsed

        return await self._chat_json_validated(
            system,
            user,
            _validate,
            temperature=QUIZ_LLM_TEMPERATURE,
            purpose=f"regenerate_quiz_question:{mode}",
        )

    async def qa_review_quiz(
        self,
        material: str,
        questions: list[dict[str, Any]],
    ) -> list[QuestionFlag]:
        """Review each question against `material` and return per-question
        flags. Pure read — no DB writes. UUIDs are taken from the input list
        (the LLM is given them only to address answers, but its echoed ids are
        ignored to avoid hallucinated values).
        """
        if not questions:
            return []

        system = _QUIZ_QA_SYSTEM
        payload = [
            {
                "question_id": str(q["id"]),
                "question": q["question"],
                "options": list(q["options"]),
                "correct_index": int(q["correct_index"]),
            }
            for q in questions
        ]
        user = (
            f"Материал:\n{material}\n\n"
            f"Вопросы (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
        )

        valid_kinds: set[FlagKind] = {"ok", "wrong_answer", "ambiguous", "duplicate"}

        def _validate(data: dict[str, Any]) -> list[QuestionFlag]:
            raw_flags = data.get("flags")
            if not isinstance(raw_flags, list):
                raise ValueError("missing 'flags' array")
            if len(raw_flags) != len(questions):
                raise ValueError(
                    f"expected {len(questions)} flags, got {len(raw_flags)}"
                )
            flags: list[QuestionFlag] = []
            for idx, item in enumerate(raw_flags):
                if not isinstance(item, dict):
                    raise ValueError(f"flag #{idx} is not an object")
                kind = item.get("kind")
                if kind not in valid_kinds:
                    raise ValueError(f"flag #{idx}: invalid kind={kind!r}")
                note = item.get("note") or ""
                if not isinstance(note, str):
                    raise ValueError(f"flag #{idx}: note must be a string")
                flags.append(
                    QuestionFlag(
                        question_id=questions[idx]["id"],
                        kind=kind,
                        note=note.strip()[:300],
                    )
                )
            return flags

        return await self._chat_json_validated(
            system,
            user,
            _validate,
            temperature=QUIZ_LLM_TEMPERATURE,
            purpose="qa_review_quiz",
        )


def _parse_question(item: Any, num_options: int) -> GeneratedQuestion:
    """Strict parser for a single quiz question from raw LLM JSON."""
    if not isinstance(item, dict):
        raise ValueError("question item is not a JSON object")
    question = item.get("question")
    options = item.get("options")
    correct_index = item.get("correct_index")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("'question' must be a non-empty string")
    if not isinstance(options, list) or len(options) != num_options:
        raise ValueError(f"'options' must be a list of exactly {num_options} strings")
    cleaned: list[str] = []
    for opt in options:
        if not isinstance(opt, str) or not opt.strip():
            raise ValueError("each option must be a non-empty string")
        cleaned.append(opt.strip())
    seen: set[str] = set()
    for opt in cleaned:
        key = opt.lower()
        if key in seen:
            raise ValueError(f"duplicate option: {opt!r}")
        seen.add(key)
    if not isinstance(correct_index, int) or isinstance(correct_index, bool):
        raise ValueError("'correct_index' must be an integer")
    if not 0 <= correct_index < num_options:
        raise ValueError(f"'correct_index' out of range: {correct_index}")
    return GeneratedQuestion(
        question=question.strip(),
        options=cleaned,
        correct_index=correct_index,
    )


_QUIZ_GENERATE_SYSTEM = """\
Ты — методист, составляющий проверочный тест по материалу лекции.
Делай ровно N вопросов с одиночным выбором (multiple choice, один правильный).
Требования:
- Все вопросы и варианты — на русском, в стиле учебной проверки понимания.
- Варианты в одном вопросе НЕ повторяются и не являются перефразом друг друга.
- Ровно K вариантов на вопрос; correct_index — индекс правильного варианта (0..K-1).
- Не задавай вопросы про оформление слайдов или мета-информацию — только про содержание.
- Не выходи за рамки предоставленного материала: не выдумывай факты.

Формат ответа — СТРОГО JSON-объект:
{"questions":[{"question":"...","options":["...","...","...","..."],"correct_index":0}, ...]}
Никакого текста вне JSON.
"""


_QUIZ_REGENERATE_SYSTEM_BASE = """\
Ты — методист, редактирующий один вопрос проверочного теста.
Сохраняй смысл вопроса в рамках предоставленного материала; не выдумывай факты.
Варианты не должны повторяться; ровно K вариантов; correct_index в диапазоне 0..K-1.

Формат ответа — СТРОГО JSON-объект:
{"question":"...","options":["...","...","..."],"correct_index":0}
Никакого текста вне JSON.
"""


_REGENERATE_MODE_RULES: dict[RegenerateMode, str] = {
    "rephrase": "Задача: перефразируй вопрос и варианты, сохраняя смысл и тот же правильный ответ.",
    "harder": (
        "Задача: сделай вопрос сложнее — более тонкая формулировка, "
        "правдоподобные дистракторы; правильный ответ по сути тот же."
    ),
    "easier": "Задача: упрости формулировку и варианты, сохрани правильный ответ.",
    "improve_distractors": (
        "Задача: оставь вопрос и правильный ответ ТЕКСТУАЛЬНО неизменными. "
        "Перепиши только неправильные варианты так, чтобы они были правдоподобны, "
        "но однозначно неверны согласно материалу."
    ),
}


_QUIZ_QA_SYSTEM = """\
Ты — рецензент тестов. Получаешь материал лекции и список вопросов с правильными ответами.
Для каждого вопроса оцени:
- "ok" — корректен, ответ соответствует материалу;
- "wrong_answer" — отмеченный correct_index НЕ является верным согласно материалу;
- "ambiguous" — несколько вариантов могут быть верны / формулировка неоднозначна;
- "duplicate" — этот вопрос дублирует другой (укажи смысловой дубликат).
Поле note: краткое (до 160 симв.) объяснение. Для "ok" — пустая строка.

Формат ответа — СТРОГО JSON:
{"flags":[{"question_id":"<uuid>","kind":"ok|wrong_answer|ambiguous|duplicate","note":"..."}, ...]}
По одному элементу на каждый вопрос, в том же порядке, что и во входе.
Никакого текста вне JSON.
"""


llm_service = LLMService()
