import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import QUIZ_MAX_MATERIAL_CHARS
from app.models.lesson import Lesson, QuizQuestion
from app.models.slide_text import SlideText
from app.schemas.quiz import GeneratedQuestion, QuizAnswerItem, QuizQuestionResult

logger = logging.getLogger(__name__)


class EmptyMaterialError(RuntimeError):
    """Raised when a lesson has no source material to build a quiz from."""


def grade_quiz(
    questions: list[QuizQuestion],
    answers: list[QuizAnswerItem],
) -> tuple[float, int, list[QuizQuestionResult]]:
    """
    Grade submitted answers against questions.

    Raises ValueError for invalid inputs:
    - answer.question_id not belonging to this lesson's questions
    - duplicate question_id in answers

    Missing answers (questions with no submitted answer) count as incorrect.
    Returns (score, correct_count, per-question results with correct_index exposed).
    """
    question_map: dict[UUID, QuizQuestion] = {q.id: q for q in questions}
    total = len(questions)

    seen: set[UUID] = set()
    for answer in answers:
        if answer.question_id not in question_map:
            raise ValueError(f"Unknown question_id: {answer.question_id}")
        if answer.question_id in seen:
            raise ValueError(f"Duplicate question_id: {answer.question_id}")
        seen.add(answer.question_id)

    answer_map: dict[UUID, int] = {a.question_id: a.selected_index for a in answers}
    results: list[QuizQuestionResult] = []
    correct_count = 0

    for question in questions:
        selected = answer_map.get(question.id)
        is_correct = selected is not None and selected == question.correct_index
        if is_correct:
            correct_count += 1
        results.append(
            QuizQuestionResult(
                question_id=question.id,
                correct=is_correct,
                correct_index=question.correct_index,
            )
        )

    score = correct_count / total if total > 0 else 0.0
    return score, correct_count, results


# ── Material assembly (priority: slides > script > text_content) ─────────────

_SLIDE_SEP = "\n\n"


def _slides_to_material(slides: list[SlideText]) -> str:
    parts: list[str] = []
    for s in sorted(slides, key=lambda r: r.slide_number):
        text = (s.edited_text or s.generated_text or "").strip()
        if text:
            parts.append(text)
    return _SLIDE_SEP.join(parts)


def _truncate(material: str, max_chars: int) -> str:
    if len(material) <= max_chars:
        return material
    logger.warning(
        "quiz material truncated from %d to %d chars", len(material), max_chars
    )
    return material[:max_chars]


async def assemble_material(
    db: AsyncSession,
    lesson: Lesson,
    *,
    max_chars: int = QUIZ_MAX_MATERIAL_CHARS,
) -> str:
    """Async (router-side) material assembly. Raises EmptyMaterialError if
    nothing usable is found.
    """
    slides_q = await db.execute(
        select(SlideText)
        .where(SlideText.lesson_id == lesson.id)
        .order_by(SlideText.slide_number)
    )
    slides = list(slides_q.scalars())
    material = _slides_to_material(slides)
    if not material:
        material = (lesson.script or "").strip()
    if not material:
        material = (lesson.text_content or "").strip()
    if not material:
        raise EmptyMaterialError("lesson has no slides, script, or text_content")
    return _truncate(material, max_chars)


def assemble_material_sync(
    session: Session,
    lesson_id: UUID,
    *,
    max_chars: int = QUIZ_MAX_MATERIAL_CHARS,
) -> str:
    """Sync (Celery-side) material assembly with identical priority."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise EmptyMaterialError(f"lesson {lesson_id} not found")
    slides = list(
        session.execute(
            select(SlideText)
            .where(SlideText.lesson_id == lesson_id)
            .order_by(SlideText.slide_number)
        ).scalars()
    )
    material = _slides_to_material(slides)
    if not material:
        material = (lesson.script or "").strip()
    if not material:
        material = (lesson.text_content or "").strip()
    if not material:
        raise EmptyMaterialError("lesson has no slides, script, or text_content")
    return _truncate(material, max_chars)


def replace_questions_sync(
    session: Session,
    lesson_id: UUID,
    items: list[GeneratedQuestion],
) -> None:
    """Atomically delete existing QuizQuestion rows for the lesson and insert
    the new batch. Caller is responsible for transactional commit semantics.
    """
    session.query(QuizQuestion).filter(QuizQuestion.lesson_id == lesson_id).delete(
        synchronize_session=False
    )
    session.flush()
    for idx, item in enumerate(items):
        session.add(
            QuizQuestion(
                lesson_id=lesson_id,
                question=item.question,
                options=list(item.options),
                correct_index=item.correct_index,
                order=idx,
            )
        )
    session.flush()
