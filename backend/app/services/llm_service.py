import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

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

C) SSML annotation — wrap the cleaned text with semantic markup. DO NOT wrap in <speak> (the system adds that). Allowed tags only:
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

    async def _chat(self, system: str, user: str, json_mode: bool = False) -> str:
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
        return response.choices[0].message.content or ""

    async def split_and_annotate_ssml(
        self,
        script: str,
        slides_count: int,
        slide_texts: list[str] | None = None,
    ) -> list[str]:
        """Split script into N chunks aligned with slides, with SSML annotation."""
        anchors = ""
        if slide_texts:
            anchor_lines = []
            for i, t in enumerate(slide_texts):
                snippet = (t or "").strip().replace("\n", " ")[:300]
                anchor_lines.append(f"Slide {i + 1}: {snippet}")
            anchors = "Slide visible texts (alignment anchors):\n" + "\n".join(anchor_lines) + "\n\n"

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
                return [str(c) for c in chunks]
            logger.warning("LLM returned %d SSML chunks for %d slides", len(chunks), slides_count)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM SSML JSON: %s", raw[:300])
        return self._fallback_ssml(script, slides_count)

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

    async def generate_quiz(
        self, lesson_text: str, questions_count: int = 5
    ) -> list[dict[str, Any]]:
        system = (
            "Generate a multiple-choice quiz from the lesson. "
            'Output JSON: {"questions": [{"question": "...", "options": ["a","b","c","d"], '
            '"correct_index": 0}, ...]}'
        )
        user = f"Questions count: {questions_count}\n\nLesson:\n{lesson_text}"

        raw = await self._chat(system, user, json_mode=True)
        try:
            data = json.loads(raw)
            return data.get("questions", [])
        except json.JSONDecodeError:
            logger.error("Failed to parse quiz JSON: %s", raw)
            return []


llm_service = LLMService()
