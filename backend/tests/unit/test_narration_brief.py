"""Author brief (Lesson.narration_brief) on the auto-mode vision path.

Guards the two halves of the contract: without a brief the prompt must stay
byte-identical to what it was before the feature; with one the brief travels as
data in the user message plus a priority section in the system prompt.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError

from app.constants import NARRATION_BRIEF_MAX_CHARS
from app.schemas.lesson import LessonUpdate
from app.services.vision_analysis import (
    VISION_SYSTEM_PROMPT,
    VisionAnalysisService,
    _build_user_content,
    _system_prompt,
)

pytestmark = pytest.mark.unit

BRIEF = "Аудитория — 9 класс. Не углубляться в математику."


@pytest.fixture()
def slide_png(tmp_path: Path) -> Path:
    p = tmp_path / "slide.png"
    Image.new("RGB", (40, 40), (180, 180, 180)).save(p, format="PNG")
    return p


def _user_text(content: list[dict[str, Any]]) -> str:
    return next(part["text"] for part in content if part["type"] == "text")


def test_system_prompt_without_brief_is_the_base_constant() -> None:
    assert _system_prompt(None) == VISION_SYSTEM_PROMPT
    assert _system_prompt("") == VISION_SYSTEM_PROMPT


def test_system_prompt_with_brief_adds_priority_section() -> None:
    prompt = _system_prompt(BRIEF)
    assert prompt.startswith(VISION_SYSTEM_PROMPT)
    assert "ПОЖЕЛАНИЯ АВТОРА:" in prompt
    assert "бюджет слов" in prompt
    # The brief itself is data in the user message, never inlined into rules.
    assert BRIEF not in prompt


def test_user_message_without_brief_has_no_author_block(slide_png: Path) -> None:
    content = _build_user_content(str(slide_png), "Курс", 1, 3, "", 200)
    assert "author_brief" not in _user_text(content)


def test_user_message_with_brief_carries_a_marked_block(slide_png: Path) -> None:
    content = _build_user_content(str(slide_png), "Курс", 1, 3, "", 200, BRIEF)
    text = _user_text(content)
    assert f"<author_brief>\n{BRIEF}\n</author_brief>" in text
    # The word budget stays where it was — a brief must not displace it.
    assert "около 200 слов" in text


async def test_analyze_slide_sends_brief_to_the_model(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    seen: dict[str, Any] = {}

    async def _create(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    svc = VisionAnalysisService()
    monkeypatch.setattr(
        svc,
        "_ollama_client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create))),
    )

    result = await svc.analyze_slide(
        slide_image_path=str(slide_png),
        slide_number=1,
        total_slides=1,
        course_title="Курс",
        narration_brief=BRIEF,
    )

    assert result == "ok"
    system, user = seen["messages"]
    assert "ПОЖЕЛАНИЯ АВТОРА:" in system["content"]
    assert BRIEF in _user_text(user["content"])


async def test_analyze_presentation_forwards_brief_to_every_slide(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    briefs: list[str | None] = []

    async def _fake_slide(**kwargs: Any) -> str:
        briefs.append(kwargs.get("narration_brief"))
        return "текст"

    svc = VisionAnalysisService()
    monkeypatch.setattr(svc, "analyze_slide", _fake_slide)

    await svc.analyze_presentation([str(slide_png), str(slide_png)], "Курс", narration_brief=BRIEF)
    assert briefs == [BRIEF, BRIEF]


def test_schema_rejects_a_brief_over_the_limit() -> None:
    with pytest.raises(ValidationError):
        LessonUpdate(narration_brief="я" * (NARRATION_BRIEF_MAX_CHARS + 1))


def test_schema_accepts_a_brief_at_the_limit() -> None:
    value = "я" * NARRATION_BRIEF_MAX_CHARS
    assert LessonUpdate(narration_brief=value).narration_brief == value


@pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
def test_schema_normalises_a_blank_brief_to_null(raw: str) -> None:
    data = LessonUpdate(narration_brief=raw)
    assert data.narration_brief is None
    # Still an explicit write — the PUT must clear the column, not skip it.
    assert "narration_brief" in data.model_dump(exclude_unset=True)
