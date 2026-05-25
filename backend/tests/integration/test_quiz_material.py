"""Material-assembly priority + truncation tests for quiz_service."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import QUIZ_MAX_MATERIAL_CHARS
from app.services.quiz_service import EmptyMaterialError, assemble_material
from tests.factories import make_course, make_lesson, make_module, make_slide_text

pytestmark = pytest.mark.integration


async def test_material_prefers_slides(
    db_session: AsyncSession, teacher_user
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, script="SCRIPT", text_content="TEXT"
    )
    await make_slide_text(
        db_session, lesson, slide_number=1, generated_text="GEN-1", edited_text=None
    )
    await make_slide_text(
        db_session, lesson, slide_number=2, generated_text="GEN-2", edited_text="EDITED-2"
    )

    material = await assemble_material(db_session, lesson)
    # Slides ordered, edited_text wins over generated_text on slide 2.
    assert material == "GEN-1\n\nEDITED-2"


async def test_material_falls_back_to_script_when_no_slides(
    db_session: AsyncSession, teacher_user
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, script="SCRIPT-BODY", text_content="TEXT-BODY"
    )

    material = await assemble_material(db_session, lesson)
    assert material == "SCRIPT-BODY"


async def test_material_falls_back_to_text_content(
    db_session: AsyncSession, teacher_user
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, script=None, text_content="TEXT-BODY")

    material = await assemble_material(db_session, lesson)
    assert material == "TEXT-BODY"


async def test_material_empty_raises(
    db_session: AsyncSession, teacher_user
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, script=None, text_content=None)

    with pytest.raises(EmptyMaterialError):
        await assemble_material(db_session, lesson)


async def test_material_truncated_to_limit(
    db_session: AsyncSession, teacher_user
) -> None:
    long_text = "A" * (QUIZ_MAX_MATERIAL_CHARS + 1000)
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, text_content=long_text)

    material = await assemble_material(db_session, lesson, max_chars=200)
    assert len(material) == 200


async def test_material_ignores_blank_slide_text(
    db_session: AsyncSession, teacher_user
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, script="SCRIPT")
    await make_slide_text(
        db_session, lesson, slide_number=1, generated_text="", edited_text=None
    )

    material = await assemble_material(db_session, lesson)
    # Blank slide doesn't suppress script fallback.
    assert material == "SCRIPT"
