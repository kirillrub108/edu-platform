"""Quiz domain helpers used by routers + Celery tasks.

Routers consume the async API; Celery uses the sync API (psycopg2). Both
paths share the material assembly logic so generation reads exactly what
the teacher sees on the page.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import QUIZ_DEFAULT_WEIGHT, QUIZ_MAX_MATERIAL_CHARS
from app.models.lesson import Lesson
from app.models.quiz import Quiz, QuizQuestion, QuizStatus
from app.models.slide_text import SlideText
from app.services.grading_service import ResolvedQuestion, snapshot_pointers

logger = logging.getLogger(__name__)


class EmptyMaterialError(RuntimeError):
    """Raised when a lesson has no source material to build a quiz from."""


class BrokenSnapshotError(RuntimeError):
    """Raised when an attempt's pointer snapshot references a (id, version)
    row that no longer exists in quiz_questions. Indicates data corruption —
    versions are never deleted by normal flows."""


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
        raise EmptyMaterialError("У урока нет материала для генерации теста: загрузите презентацию или добавьте текст урока")
    return _truncate(material, max_chars)


def assemble_material_sync(
    session: Session,
    lesson_id: UUID,
    *,
    max_chars: int = QUIZ_MAX_MATERIAL_CHARS,
) -> str:
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
        raise EmptyMaterialError("У урока нет материала для генерации теста: загрузите презентацию или добавьте текст урока")
    return _truncate(material, max_chars)


# ── Quiz lifecycle helpers ───────────────────────────────────────────────────


async def get_or_create_quiz(db: AsyncSession, lesson: Lesson) -> Quiz:
    """Return the lesson's Quiz (create draft if missing). Routers call this
    on first GET so the teacher gets a stable object to attach questions to.

    NOTE: do NOT short-circuit on `lesson.quiz` — that's a lazy relationship
    and dereferencing it inside async context triggers `MissingGreenlet`.
    The unique constraint `uq_quizzes_lesson_id` also means two parallel
    requests on first load can race: both SELECT None, both INSERT, one
    fails. We catch the resulting IntegrityError and re-select.
    """
    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson.id))
    if quiz is not None:
        return quiz
    quiz = Quiz(lesson_id=lesson.id)
    db.add(quiz)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson.id))
        if quiz is None:
            raise  # Real integrity error, not the race we expected
        return quiz
    await db.refresh(quiz)
    return quiz


def get_or_create_quiz_sync(session: Session, lesson_id: UUID) -> Quiz:
    quiz = session.execute(
        select(Quiz).where(Quiz.lesson_id == lesson_id)
    ).scalar_one_or_none()
    if quiz is None:
        quiz = Quiz(lesson_id=lesson_id)
        session.add(quiz)
        session.flush()
    return quiz


def replace_questions_sync(
    session: Session,
    quiz_id: UUID,
    items: list[dict[str, Any]],
) -> None:
    """Replace the current set of questions for a quiz with a freshly
    generated batch. Implements the versioned write protocol:

      * every current row gets `superseded_at = now()` (soft-delete);
      * every new question is inserted at `version = 1` with a fresh id.

    Historical versions stay readable for attempts that pinned them; their
    snapshots still resolve.
    """
    now = datetime.now(timezone.utc)
    session.query(QuizQuestion).filter(
        QuizQuestion.quiz_id == quiz_id,
        QuizQuestion.superseded_at.is_(None),
    ).update({QuizQuestion.superseded_at: now}, synchronize_session=False)
    session.flush()
    for idx, item in enumerate(items):
        session.add(
            QuizQuestion(
                quiz_id=quiz_id,
                type=item["type"],
                payload=item["payload"],
                weight=Decimal(str(item.get("weight", "1.0"))),
                order=item.get("order", idx),
            )
        )
    session.flush()


def has_published_questions(quiz: Quiz) -> bool:
    return quiz.status == QuizStatus.published and bool(quiz.questions)


# ── Versioned-question write helpers (insert-on-write + supersede) ──────────
#
# Invariant: a question's `payload` / `weight` / `type` row is immutable.
# Any meaningful edit creates a new row with `version = current_version + 1`
# (same `id`) and sets the predecessor's `superseded_at = now()`. The two
# writes happen inside one transaction so the "exactly one current version"
# invariant holds even under concurrent edits.
#
# `order` and soft-delete are recorded in place on the current row by design:
# order is part of the attempt snapshot anyway, and a delete only flips
# `superseded_at` (no successor row).


async def load_current_question(
    db: AsyncSession, quiz_id: UUID, question_id: UUID
) -> QuizQuestion | None:
    return await db.scalar(
        select(QuizQuestion).where(
            QuizQuestion.id == question_id,
            QuizQuestion.quiz_id == quiz_id,
            QuizQuestion.superseded_at.is_(None),
        )
    )


async def supersede_with_new_version(
    db: AsyncSession,
    current: QuizQuestion,
    *,
    payload: dict[str, Any] | None = None,
    weight: Decimal | None = None,
    question_type: Any | None = None,
) -> QuizQuestion:
    """Insert version = current.version + 1, then mark `current` superseded.

    Reuses the current row's `id` (composite PK is `(id, version)`) so
    pointers from existing attempts still find their pinned version.
    """
    new_row = QuizQuestion(
        id=current.id,
        version=current.version + 1,
        quiz_id=current.quiz_id,
        type=question_type if question_type is not None else current.type,
        payload=payload if payload is not None else dict(current.payload),
        weight=weight if weight is not None else current.weight,
        order=current.order,
    )
    db.add(new_row)
    current.superseded_at = datetime.now(timezone.utc)
    await db.flush()
    return new_row


# ── Snapshot resolver ──────────────────────────────────────────────────────
#
# A pointer snapshot is JSONB of shape
#   {"version": 1, "pointers": [{"question_id", "version", "order"}, ...]}.
# Resolving it = batch-loading the matching (id, version) rows from
# quiz_questions, then producing ResolvedQuestion in pointer order. We
# always return in snapshot order (so grading + UI both see attempt order).


def _pairs_from_snapshot(snapshot: dict[str, Any]) -> list[tuple[UUID, int]]:
    out: list[tuple[UUID, int]] = []
    for p in snapshot_pointers(snapshot):
        out.append((UUID(str(p["question_id"])), int(p["version"])))
    return out


def _to_resolved(
    pointers: list[dict[str, Any]],
    rows_by_pk: dict[tuple[UUID, int], QuizQuestion],
) -> list[ResolvedQuestion]:
    out: list[ResolvedQuestion] = []
    for ptr in pointers:
        qid = UUID(str(ptr["question_id"]))
        ver = int(ptr["version"])
        row = rows_by_pk.get((qid, ver))
        if row is None:
            raise BrokenSnapshotError(
                f"snapshot references missing question version: {qid}@{ver}"
            )
        out.append(
            ResolvedQuestion(
                id=row.id,
                version=row.version,
                type=row.type.value if hasattr(row.type, "value") else str(row.type),
                payload=dict(row.payload),
                weight=Decimal(str(row.weight)) if row.weight is not None
                else Decimal(str(QUIZ_DEFAULT_WEIGHT)),
                order=int(ptr.get("order", row.order)),
            )
        )
    return out


def _row_pk(row: QuizQuestion) -> tuple[UUID, int]:
    return (row.id, int(row.version))


async def resolve_snapshot(
    db: AsyncSession, snapshot: dict[str, Any]
) -> list[ResolvedQuestion]:
    pointers = snapshot_pointers(snapshot)
    if not pointers:
        return []
    pairs = _pairs_from_snapshot(snapshot)
    # tuple_().in_(VALUES) — single batched lookup of (id, version) pairs.
    rows_q = await db.execute(
        select(QuizQuestion).where(
            tuple_(QuizQuestion.id, QuizQuestion.version).in_(pairs)
        )
    )
    rows_by_pk = {_row_pk(r): r for r in rows_q.scalars()}
    return _to_resolved(pointers, rows_by_pk)


def resolve_snapshot_sync(
    session: Session, snapshot: dict[str, Any]
) -> list[ResolvedQuestion]:
    pointers = snapshot_pointers(snapshot)
    if not pointers:
        return []
    pairs = _pairs_from_snapshot(snapshot)
    rows = session.execute(
        select(QuizQuestion).where(
            tuple_(QuizQuestion.id, QuizQuestion.version).in_(pairs)
        )
    ).scalars().all()
    rows_by_pk = {_row_pk(r): r for r in rows}
    return _to_resolved(pointers, rows_by_pk)
