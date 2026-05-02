import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


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
            "temperature": 0.4,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def split_text_by_slides(self, text: str, slides_count: int) -> list[str]:
        system = (
            "You split lecture transcripts into N chunks (one per slide). "
            "Output strictly a JSON object: {\"chunks\": [\"...\", \"...\"]} with exactly N items."
        )
        user = f"Slides count: {slides_count}\n\nTranscript:\n{text}"

        raw = await self._chat(system, user, json_mode=True)
        try:
            data = json.loads(raw)
            chunks = data.get("chunks", [])
            if len(chunks) != slides_count:
                logger.warning("LLM returned %d chunks, expected %d", len(chunks), slides_count)
            return [str(c) for c in chunks]
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM JSON: %s", raw)
            return [text] * slides_count

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
