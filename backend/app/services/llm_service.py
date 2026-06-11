import json
import structlog
import re
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.config import provider_routing, settings
from app.constants import (
    LLM_MAX_RETRIES,
    LLM_REQUEST_TIMEOUT_SECONDS,
    QUIZ_LLM_OPEN_MAX_TOKENS,
    QUIZ_LLM_TEMPERATURE,
    QUIZ_MIN_FOR_DISTRIBUTION,
    QUIZ_TYPE_DISTRIBUTION,
)
from app.schemas.quiz import FlagKind, QuestionFlag, RegenerateMode
from app.services import usage_service

logger = structlog.get_logger()


def _compute_type_counts(n: int, types: list[str]) -> dict[str, int]:
    """Return how many questions of each type to request.

    If n < QUIZ_MIN_FOR_DISTRIBUTION or types has only one entry, all n go to
    types[0]. Otherwise uses QUIZ_TYPE_DISTRIBUTION for the known four types,
    with short_answer absorbing the rounding remainder.
    """
    if n < QUIZ_MIN_FOR_DISTRIBUTION or len(types) == 1:
        return {types[0]: n}

    ordered = ["single_choice", "multiple_choice", "true_false", "short_answer"]
    active = [t for t in ordered if t in types]
    if len(active) < 2:
        return {types[0]: n}

    counts: dict[str, int] = {}
    for t in active[:-1]:
        frac = QUIZ_TYPE_DISTRIBUTION.get(t, 0.0)
        counts[t] = round(n * frac)
    counts[active[-1]] = n - sum(counts.values())
    # Clamp negatives from extreme rounding.
    for t in active:
        counts[t] = max(0, counts[t])
    return counts


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
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        self.model = settings.LLM_MODEL
        self._provider_extra = provider_routing(settings.LLM_PROVIDER_ORDER)

    def _apply_provider(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Inject the Polza provider-routing pin into a request, if configured."""
        if self._provider_extra:
            kwargs["extra_body"] = self._provider_extra
        return kwargs

    @staticmethod
    def _strip_think(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove a wrapping markdown code fence (```json … ```) that some cloud
        models emit around JSON despite response_format=json_object. Local Ollama
        never does this, so the strip is a no-op for it. <think> blocks are
        already removed upstream in _chat."""
        t = text.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[A-Za-z0-9]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        return t.strip()

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

        response = await self.client.chat.completions.create(**self._apply_provider(kwargs))
        await usage_service.arecord_llm_usage(kwargs["model"], getattr(response, "usage", None))
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
                data = json.loads(self._strip_code_fences(raw))
                return validator(data)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "llm_malformed_output",
                    purpose=purpose,
                    attempt=attempt + 1,
                    error=str(exc),
                    raw=raw[:300],
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
            data = json.loads(self._strip_code_fences(raw))
            chunks = data.get("chunks", [])
            if len(chunks) == slides_count and all(chunks):
                return [str(c) for c in chunks], None
            got = len(chunks)
            logger.warning("llm_ssml_chunk_mismatch", got=got, expected=slides_count)
            warning = (
                f"LLM вернул {got} чанков вместо {slides_count}. "
                "Использован fallback — качество озвучки может быть ниже."
            )
        except json.JSONDecodeError:
            logger.error("llm_ssml_json_parse_failed", raw=raw[:300])
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
        response = await self.client.chat.completions.create(**self._apply_provider(kwargs))
        await usage_service.arecord_llm_usage(self.model, getattr(response, "usage", None))
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
        logger.debug("refine_slide_narration", model=model)
        return await self._chat(system, vision_text, model=model)

    async def generate_quiz_v2(
        self,
        material: str,
        *,
        num_questions: int,
        num_options: int,
        types: list[str],
    ) -> list[dict[str, Any]]:
        """Generate a polymorphic quiz strictly grounded in `material`.

        Returns a list of {type, payload, weight, order} dicts whose payloads
        match the discriminated schema in `schemas.quiz`. Raises LLMOutputError
        if the LLM refuses well-formed output after one retry.

        The system prompt explicitly forbids fabricating facts/standards/IDs
        beyond what `material` contains — this is the fix for the "ГОСТ Р ИСО
        2150N" / "548NN" hallucinations seen in the v1 generator.
        """
        if not types:
            types = ["single_choice"]
        type_counts = _compute_type_counts(num_questions, types)

        # Build a human-readable breakdown line for the prompt.
        _type_labels = {
            "single_choice": "single-choice",
            "multiple_choice": "multiple-choice",
            "true_false": "true/false",
            "short_answer": "short-answer (fill-in-the-blank)",
        }
        breakdown = ", ".join(
            f"{cnt} {_type_labels.get(t, t)}"
            for t, cnt in type_counts.items()
            if cnt > 0
        )
        user = (
            f"Кол-во вопросов: {num_questions} ({breakdown})\n"
            f"Разрешённые типы: {', '.join(t for t, c in type_counts.items() if c > 0)}\n"
            f"Для multiple/single choice: {num_options} вариантов.\n\n"
            f"Материал:\n{material}"
        )

        def _validate(data: dict[str, Any]) -> list[dict[str, Any]]:
            raw_questions = data.get("questions")
            if not isinstance(raw_questions, list) or not raw_questions:
                raise ValueError("missing or empty 'questions' array")
            if len(raw_questions) != num_questions:
                raise ValueError(
                    f"expected {num_questions} questions, got {len(raw_questions)}"
                )
            out: list[dict[str, Any]] = []
            actual_counts: dict[str, int] = {}
            for idx, item in enumerate(raw_questions):
                if not isinstance(item, dict):
                    raise ValueError(f"q{idx}: not an object")
                qtype = item.get("type")
                if qtype not in types:
                    raise ValueError(f"q{idx}: disallowed type {qtype!r}")
                payload = _parse_payload_v2(qtype, item, num_options)
                out.append({
                    "type": qtype,
                    "payload": payload,
                    "weight": "1.0",
                    "order": idx,
                })
                actual_counts[qtype] = actual_counts.get(qtype, 0) + 1
            # Warn if the LLM deviated from the requested distribution.
            for t, want in type_counts.items():
                got = actual_counts.get(t, 0)
                if want > 0 and got != want:
                    logger.warning(
                        "quiz_type_count_mismatch", q_type=t, requested=want, got=got
                    )
            return out

        return await self._chat_json_validated(
            _QUIZ_GENERATE_V2_SYSTEM,
            user,
            _validate,
            temperature=QUIZ_LLM_TEMPERATURE,
            purpose="generate_quiz_v2",
        )

    async def grade_open_answer(
        self,
        question_payload: dict[str, Any],
        response_text: str,
    ) -> tuple[float, str]:
        """LLM-grade a short_answer or essay response against the question's
        reference/rubric. Returns (score_0_to_1, feedback).
        """
        qtype = question_payload.get("type")
        prompt = question_payload.get("prompt", "")
        rubric = question_payload.get("rubric", "")
        reference = question_payload.get("reference_answer", "")

        user = (
            f"Тип: {qtype}\n"
            f"Вопрос: {prompt}\n"
            f"Эталон/критерии: {reference or rubric}\n"
            f"Ответ студента: {response_text or '[пустой]'}"
        )

        def _validate(data: dict[str, Any]) -> tuple[float, str]:
            score = data.get("score")
            feedback = data.get("feedback", "")
            if not isinstance(score, (int, float)):
                raise ValueError("score must be a number")
            if not 0 <= float(score) <= 1:
                raise ValueError("score must be within [0, 1]")
            if not isinstance(feedback, str):
                raise ValueError("feedback must be a string")
            return float(score), feedback.strip()[:600]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _OPEN_GRADE_SYSTEM},
                {"role": "user", "content": user + "\n/no_think"},
            ],
            "temperature": QUIZ_LLM_TEMPERATURE,
            "max_tokens": QUIZ_LLM_OPEN_MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        # Bypass _chat to enforce max_tokens; retry on malformed once.
        self._apply_provider(kwargs)
        last_error: str | None = None
        for attempt in range(2):
            response = await self.client.chat.completions.create(**kwargs)
            await usage_service.arecord_llm_usage(self.model, getattr(response, "usage", None))
            raw = self._strip_think(response.choices[0].message.content or "")
            if not raw.strip():
                last_error = "empty response after strip_think"
                logger.warning("grade_open_answer_empty_raw", attempt=attempt + 1)
                continue
            try:
                return _validate(json.loads(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "grade_open_answer_malformed",
                    attempt=attempt + 1,
                    error=str(exc),
                    raw=raw[:300],
                )
        raise LLMOutputError(f"grade_open_answer: invalid output: {last_error}")

    async def regenerate_quiz_question(
        self,
        material: str,
        question: dict[str, Any],
        mode: RegenerateMode,
        num_options: int,
    ) -> dict[str, Any]:
        """Apply a single-question transformation. Currently supports only
        single_choice payloads — multi/true_false/open types are out of scope
        for one-click regenerate. For `improve_distractors` the correct
        option text must remain identical.

        Returns a NEW payload dict (same type contract), not a model instance.
        """
        qtype = question.get("type")
        if qtype != "single_choice":
            raise ValueError(
                f"regenerate is currently only supported for single_choice (got {qtype})"
            )
        options = question.get("options") or []
        correct_index = int(question.get("correct_index", 0))
        if not 0 <= correct_index < len(options):
            raise ValueError("regenerate: malformed source question")

        system = _QUIZ_REGENERATE_SYSTEM_BASE + "\n\n" + _REGENERATE_MODE_RULES[mode]
        current = {
            "question": question.get("prompt", ""),
            "options": list(options),
            "correct_index": correct_index,
        }
        user = (
            f"Кол-во вариантов: {num_options}\n\n"
            f"Материал:\n{material}\n\n"
            f"Текущий вопрос (JSON):\n{json.dumps(current, ensure_ascii=False)}"
        )
        expected_correct = options[correct_index].strip().lower()

        def _validate(data: dict[str, Any]) -> dict[str, Any]:
            payload = _parse_payload_v2("single_choice", {
                "type": "single_choice",
                "prompt": data.get("question"),
                "options": data.get("options"),
                "correct_index": data.get("correct_index"),
            }, num_options)
            if mode == "improve_distractors":
                got = payload["options"][payload["correct_index"]].strip().lower()
                if got != expected_correct:
                    raise ValueError(
                        "improve_distractors must preserve the correct option text"
                    )
            return payload

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

        Input `questions` must be a list of {id, type, payload} dicts; the
        full reference-answer-bearing payload is sent (this is teacher-side).
        """
        if not questions:
            return []

        system = _QUIZ_QA_SYSTEM
        payload = [
            {
                "question_id": str(q["id"]),
                "type": q["type"],
                "payload": q["payload"],
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


def _check_options(options: Any, num_options: int) -> list[str]:
    if not isinstance(options, list) or len(options) != num_options:
        raise ValueError(f"'options' must be a list of exactly {num_options} strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for opt in options:
        if not isinstance(opt, str) or not opt.strip():
            raise ValueError("each option must be a non-empty string")
        key = opt.strip().lower()
        if key in seen:
            raise ValueError(f"duplicate option: {opt!r}")
        seen.add(key)
        cleaned.append(opt.strip())
    return cleaned


def _parse_payload_v2(qtype: str, item: dict[str, Any], num_options: int) -> dict[str, Any]:
    """Parse + validate a single LLM-emitted payload by type. Raises ValueError
    on shape problems so the JSON-validated retry kicks in."""
    prompt = item.get("prompt") or item.get("question")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' must be a non-empty string")
    prompt = prompt.strip()

    if qtype == "single_choice":
        opts = _check_options(item.get("options"), num_options)
        ci = item.get("correct_index")
        if not isinstance(ci, int) or isinstance(ci, bool) or not 0 <= ci < num_options:
            raise ValueError(f"'correct_index' out of range: {ci}")
        return {"type": qtype, "prompt": prompt, "options": opts, "correct_index": ci, "explanation": ""}

    if qtype == "multiple_choice":
        opts = _check_options(item.get("options"), num_options)
        raw = item.get("correct_indices")
        if not isinstance(raw, list) or not raw:
            raise ValueError("'correct_indices' must be a non-empty list")
        seen: set[int] = set()
        for i in raw:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < num_options:
                raise ValueError(f"correct_indices contains invalid index: {i}")
            seen.add(i)
        if len(seen) == num_options:
            raise ValueError("multiple_choice cannot have all options correct")
        return {
            "type": qtype, "prompt": prompt, "options": opts,
            "correct_indices": sorted(seen), "explanation": "",
        }

    if qtype == "true_false":
        correct = item.get("correct")
        if not isinstance(correct, bool):
            raise ValueError("'correct' must be a boolean")
        return {"type": qtype, "prompt": prompt, "correct": correct, "explanation": ""}

    if qtype == "short_answer":
        ref = item.get("reference_answer")
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("'reference_answer' must be a non-empty string")
        rubric = item.get("rubric") or ""
        return {
            "type": qtype, "prompt": prompt,
            "reference_answer": ref.strip(),
            "rubric": str(rubric).strip(),
        }

    raise ValueError(f"unsupported generated type: {qtype!r}")


_QUIZ_GENERATE_V2_SYSTEM = """\
Ты — методист, составляющий проверочный тест по материалу лекции.
Делай РОВНО N вопросов, ТОЛЬКО разрешённых типов.

КРИТИЧНО: НЕ выдумывай факты, термины, стандарты, ГОСТы, номера, имена,
формулы, даты, проценты, аббревиатуры, которых НЕТ в исходном тексте.
Если материал не позволяет составить достаточно вопросов по содержанию —
сделай столько, на сколько хватает фактического материала, и заполни
оставшиеся пересказом существующих идей другими словами.
ЗАПРЕЩЕНО: придумывать обозначения типа «ГОСТ Р ИСО 2150N», «548NN», и
любые вымышленные коды/индексы.

Все вопросы и варианты — на русском, в стиле учебной проверки понимания.
Не задавай вопросов про оформление слайдов или мета-информацию (нумерация,
названия слайдов и т.п.) — только про содержание.

Формат для каждого типа в массиве questions:
  - single_choice:
      {"type":"single_choice","prompt":"...","options":["..."],"correct_index":0}
      Ровно K вариантов; варианты не повторяются и не парафразят друг друга.
  - multiple_choice:
      {"type":"multiple_choice","prompt":"...","options":["..."],"correct_indices":[0,2]}
      Ровно K вариантов; верных — от 1 до K-1; индексы уникальны.
  - true_false:
      {"type":"true_false","prompt":"...","correct":true}
      prompt должен быть однозначным утверждением (без «возможно», «иногда»).
  - short_answer:
      {"type":"short_answer","prompt":"...","reference_answer":"...","rubric":"..."}
      reference_answer — короткий точный ответ (1-15 слов).

Формат ответа — СТРОГО JSON-объект (без текста вне JSON):
{"questions":[ ... ровно N элементов ... ]}
"""


_OPEN_GRADE_SYSTEM = """\
Ты — оценщик коротких/развёрнутых ответов студентов. Сравни ответ студента
с эталоном и/или критериями. Поставь дробную оценку от 0.0 до 1.0
(включительно): 0 — полностью неверно/пусто, 1 — полностью соответствует
эталону по сути (необязательно дословно). Частичное соответствие — дробь.

Никогда не цитируй эталон/правильный ответ в feedback — только опиши, что
у студента верно/неверно, не раскрывая reference_answer.

Формат — СТРОГО JSON:
{"score": 0.7, "feedback": "Краткое объяснение (1-2 предложения, без цитат эталона)."}
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
Ты — рецензент тестов. Получаешь материал лекции и список вопросов с эталонами.
Для каждого вопроса оцени:
- "ok" — корректен, эталон соответствует материалу;
- "wrong_answer" — указанный эталон НЕ соответствует материалу;
- "ambiguous" — формулировка неоднозначна или несколько вариантов могут быть верны;
- "duplicate" — этот вопрос дублирует другой по смыслу (укажи в note кого).
Поле note: краткое (до 160 симв.) объяснение. Для "ok" — пустая строка.
ВАЖНО: ни в коем случае не выдумывай факты, отсутствующие в материале.

Формат ответа — СТРОГО JSON:
{"flags":[{"question_id":"<uuid>","kind":"ok|wrong_answer|ambiguous|duplicate","note":"..."}, ...]}
По одному элементу на каждый вопрос, в том же порядке, что и во входе.
Никакого текста вне JSON.
"""


llm_service = LLMService()
