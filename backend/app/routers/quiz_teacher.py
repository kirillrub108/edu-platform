"""Teacher-side quiz endpoints — authoring + AI ops + manual override.

Per-quiz settings, polymorphic question CRUD, publish/unpublish (independent
of Lesson.status), LLM generation/regeneration/QA, and the manual override
that re-aggregates the student's attempt score atomically.
"""
from __future__ import annotations

import structlog
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.constants import (
    CREDIT_WEIGHTS,
    QUIZ_DEFAULT_WEIGHT,
    QUIZ_NUM_OPTIONS,
    QUIZ_NUM_QUESTIONS,
    QUIZ_PASS_THRESHOLD,
    QUIZ_TYPE_DISTRIBUTION,
)
from app.database import get_db
from app.dependencies import get_owned_lesson, require_verified_email
from app.limiter import limiter
from app.models.credit import CreditOperation
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson, Module
from app.models.quiz import (
    AttemptStatus,
    Quiz,
    QuizAnswer,
    QuizAttempt,
    QuizQuestion,
    QuizStatus,
)
from app.models.user import User
from app.schemas.quiz import (
    AnswerOverride,
    GradeOverride,
    GradeOverrideResponse,
    QuestionFlag,
    QuizAttemptTeacherDetail,
    QuizAttemptTeacherRead,
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizGenerationStatus,
    QuizQuestionCreate,
    QuizQuestionReorder,
    QuizQuestionTeacherRead,
    QuizQuestionUpdate,
    QuizRead,
    QuizRegenerateRequest,
    QuizSettingsUpdate,
)
from app.services import billing_service, quota_service, usage_service
from app.services.grading_service import aggregate_score, resolved_index
from app.services.llm_service import LLMOutputError, llm_service
from app.services.quiz_service import (
    BrokenSnapshotError,
    EmptyMaterialError,
    assemble_material,
    get_or_create_quiz,
    load_current_question,
    resolve_snapshot,
    supersede_with_new_version,
)
from app.tasks.quiz_pipeline import generate_quiz_task

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/lessons", tags=["quiz-teacher"])

_OPEN_ENDED_TYPES = {"short_answer", "essay"}


async def _load_question(
    db: AsyncSession, quiz_id: UUID, question_id: UUID
) -> QuizQuestion:
    """Load the CURRENT (non-superseded) version of a question. Historical
    versions stay in the table for attempt snapshots but are not addressable
    via the teacher API.
    """
    row = await load_current_question(db, quiz_id, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Quiz question not found")
    return row


async def _load_lesson_quiz(db: AsyncSession, lesson: Lesson) -> Quiz:
    """Eager-load .questions so callers don't trigger lazy loads inside async.

    Lazy creation on first GET happens via the shared helper, which handles
    the race against parallel first-load requests (uq_quizzes_lesson_id).
    """
    q = await db.scalar(
        select(Quiz)
        .where(Quiz.lesson_id == lesson.id)
        .options(selectinload(Quiz.questions))
    )
    if q is not None:
        return q
    await get_or_create_quiz(db, lesson)
    # Re-SELECT with selectinload so the relationship is hydrated for callers.
    q = await db.scalar(
        select(Quiz)
        .where(Quiz.lesson_id == lesson.id)
        .options(selectinload(Quiz.questions))
    )
    assert q is not None
    return q


# ── Quiz settings ───────────────────────────────────────────────────────────


@router.get("/{lesson_id}/quiz", response_model=QuizRead)
async def get_quiz(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizRead:
    quiz = await _load_lesson_quiz(db, lesson)
    return QuizRead.model_validate(quiz)


@router.put("/{lesson_id}/quiz", response_model=QuizRead)
async def update_quiz_settings(
    lesson_id: UUID,
    data: QuizSettingsUpdate,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizRead:
    quiz = await _load_lesson_quiz(db, lesson)
    if data.attempts_allowed != "__unset__":
        quiz.attempts_allowed = data.attempts_allowed  # type: ignore[assignment]
    if data.pass_threshold is not None:
        quiz.pass_threshold = data.pass_threshold
    if data.show_answers is not None:
        quiz.show_answers = data.show_answers
    if data.shuffle is not None:
        quiz.shuffle = data.shuffle
    await db.commit()
    await db.refresh(quiz)
    return QuizRead.model_validate(quiz)


@router.post("/{lesson_id}/quiz/publish", response_model=QuizRead)
async def publish_quiz(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizRead:
    quiz = await _load_lesson_quiz(db, lesson)
    if not quiz.questions:
        raise HTTPException(status_code=409, detail="Cannot publish an empty quiz")
    quiz.status = QuizStatus.published
    await db.commit()
    await db.refresh(quiz)
    return QuizRead.model_validate(quiz)


@router.post("/{lesson_id}/quiz/unpublish", response_model=QuizRead)
async def unpublish_quiz(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizRead:
    quiz = await _load_lesson_quiz(db, lesson)
    quiz.status = QuizStatus.draft
    await db.commit()
    await db.refresh(quiz)
    return QuizRead.model_validate(quiz)


# ── Question CRUD ───────────────────────────────────────────────────────────


@router.get("/{lesson_id}/quiz/questions", response_model=list[QuizQuestionTeacherRead])
async def list_questions(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuizQuestionTeacherRead]:
    quiz = await _load_lesson_quiz(db, lesson)
    rows = await db.execute(
        select(QuizQuestion)
        .where(
            QuizQuestion.quiz_id == quiz.id,
            QuizQuestion.superseded_at.is_(None),
        )
        .order_by(QuizQuestion.order, QuizQuestion.created_at)
    )
    return [QuizQuestionTeacherRead.model_validate(r) for r in rows.scalars()]


@router.post(
    "/{lesson_id}/quiz/questions",
    response_model=QuizQuestionTeacherRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    lesson_id: UUID,
    data: QuizQuestionCreate,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestionTeacherRead:
    quiz = await _load_lesson_quiz(db, lesson)
    # Append to the end if order not specified. Only current rows contribute
    # to the visible order.
    max_order = await db.scalar(
        select(func.max(QuizQuestion.order)).where(
            QuizQuestion.quiz_id == quiz.id,
            QuizQuestion.superseded_at.is_(None),
        )
    )
    next_order = data.order if data.order > 0 else (max_order or 0) + 1
    row = QuizQuestion(
        quiz_id=quiz.id,
        type=data.type,
        payload=data.payload.model_dump(),
        weight=data.weight,
        order=next_order,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return QuizQuestionTeacherRead.model_validate(row)


@router.patch(
    "/{lesson_id}/quiz/questions/{question_id}",
    response_model=QuizQuestionTeacherRead,
)
async def update_question(
    lesson_id: UUID,
    question_id: UUID,
    data: QuizQuestionUpdate,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestionTeacherRead:
    """Apply a teacher edit.

    Payload / weight changes are immutable on the current row — instead we
    insert a new (id, version+1) row and supersede the predecessor (atomic
    in one transaction). `order` is part of the snapshot and may change
    in place on the current row without bumping the version.
    """
    quiz = await _load_lesson_quiz(db, lesson)
    current = await _load_question(db, quiz.id, question_id)

    new_payload = data.payload.model_dump() if data.payload is not None else None
    weight = data.weight
    bumps_version = new_payload is not None or weight is not None

    if bumps_version:
        new_row = await supersede_with_new_version(
            db, current, payload=new_payload, weight=weight,
        )
        # Order is a property of the visible row; it doesn't bump the version
        # but we still want to apply it to the new current row.
        if data.order is not None:
            new_row.order = data.order
        target = new_row
    else:
        if data.order is not None:
            current.order = data.order
        target = current

    await db.commit()
    await db.refresh(target)
    return QuizQuestionTeacherRead.model_validate(target)


@router.delete(
    "/{lesson_id}/quiz/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    lesson_id: UUID,
    question_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete: stamp `superseded_at = now()` on the current version.

    Hard delete is unsafe — existing attempts pin (id, version) pairs in
    their snapshots and must remain resolvable.
    """
    quiz = await _load_lesson_quiz(db, lesson)
    row = await _load_question(db, quiz.id, question_id)
    row.superseded_at = datetime.now(timezone.utc)
    await db.commit()


@router.post(
    "/{lesson_id}/quiz/questions/reorder",
    response_model=list[QuizQuestionTeacherRead],
)
async def reorder_questions(
    lesson_id: UUID,
    data: QuizQuestionReorder,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuizQuestionTeacherRead]:
    quiz = await _load_lesson_quiz(db, lesson)
    rows_q = await db.execute(
        select(QuizQuestion).where(
            QuizQuestion.quiz_id == quiz.id,
            QuizQuestion.superseded_at.is_(None),
        )
    )
    rows = {r.id: r for r in rows_q.scalars()}
    if set(rows.keys()) != set(data.order):
        raise HTTPException(
            status_code=400,
            detail="reorder list must contain exactly the existing question ids",
        )
    # Reorder mutates the current row in place — order isn't payload, so no
    # version bump.
    for idx, qid in enumerate(data.order):
        rows[qid].order = idx + 1
    await db.commit()
    refreshed = await db.execute(
        select(QuizQuestion)
        .where(
            QuizQuestion.quiz_id == quiz.id,
            QuizQuestion.superseded_at.is_(None),
        )
        .order_by(QuizQuestion.order)
    )
    return [QuizQuestionTeacherRead.model_validate(r) for r in refreshed.scalars()]


# ── AI: generate / regenerate / qa-review ──────────────────────────────────


@router.post(
    "/{lesson_id}/quiz/generate",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/minute")
async def generate_quiz(
    request: Request,
    lesson_id: UUID,
    payload: QuizGenerateRequest,
    user: User = Depends(require_verified_email),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizGenerateResponse:
    num_questions = payload.num_questions or QUIZ_NUM_QUESTIONS
    num_options = payload.num_options or QUIZ_NUM_OPTIONS
    types: list[str] = list(payload.types) if payload.types else list(QUIZ_TYPE_DISTRIBUTION.keys())

    try:
        await assemble_material(db, lesson)
    except EmptyMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    quiz = await get_or_create_quiz(db, lesson)

    # Concurrency (read): one active generation per quiz.
    if quiz.generation_task_id:
        raise HTTPException(status_code=409, detail={"code": "generation_in_progress"})

    # Trial quiz slot or full-price reservation (regeneration costs the same).
    estimate = CREDIT_WEIGHTS["quiz_generate"]
    balance = await billing_service.get_balance(db, user.id)
    trial = await quota_service.get_trial_state(db, user.id)
    billing_ref = f"quiz:{quiz.id}:{uuid4().hex[:12]}"
    billed_via = "credits"
    if (
        balance["plan"] == "free"
        and trial["quizzes_used"] < trial["quizzes_limit"]
        and await quota_service.try_consume_slot(
            db, user.id, quota_service.TRIAL_QUIZ, trial["quizzes_limit"]
        )
    ):
        billed_via = "trial"
    elif not await billing_service.reserve_credits(
        db, user.id, estimate, billing_ref, CreditOperation.QUIZ_GENERATE
    ):
        if balance["plan"] == "free" and trial["quizzes_used"] >= trial["quizzes_limit"]:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "trial_exhausted",
                    "limit": trial["quizzes_limit"],
                    "used": trial["quizzes_used"],
                },
            )
        raise HTTPException(
            status_code=402,
            detail={
                "code": "insufficient_credits",
                "required": estimate,
                "available": balance["available"],
            },
        )

    try:
        task = generate_quiz_task.apply_async(
            args=[str(lesson.id), num_questions, num_options, types],
            kwargs={
                "billing_ref": billing_ref,
                "billed_via": billed_via,
                "owner_id": str(user.id),
            },
            queue="quiz",
        )
    except Exception:
        if billed_via == "credits":
            await billing_service.release_credits(db, user.id, estimate, billing_ref)
        else:
            await quota_service.release_slot(db, user.id, quota_service.TRIAL_QUIZ)
        raise HTTPException(status_code=503, detail="Не удалось поставить задачу в очередь")
    quiz.generation_task_id = task.id
    await db.commit()
    return QuizGenerateResponse(task_id=task.id, quiz_id=quiz.id, lesson_id=lesson.id)


@router.get(
    "/{lesson_id}/quiz/generation-status/{task_id}",
    response_model=QuizGenerationStatus,
)
async def quiz_generation_status(
    lesson_id: UUID,
    task_id: str,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizGenerationStatus:
    # generate_quiz_task clears Quiz.generation_task_id on finish (success AND
    # failure), so "generation_task_id != this task" is a DB-authoritative
    # "this task is done" signal that survives a Redis restart — unlike
    # AsyncResult, which reports PENDING for a finished task once Redis is wiped.
    # Success vs failure is told apart by whether current questions exist;
    # AsyncResult is consulted only for live progress and the failure error text.
    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson.id))
    result = AsyncResult(task_id, app=celery_app)

    if quiz is not None and quiz.generation_task_id != task_id:
        current_questions = await db.scalar(
            select(func.count())
            .select_from(QuizQuestion)
            .where(
                QuizQuestion.quiz_id == quiz.id,
                QuizQuestion.superseded_at.is_(None),
            )
        )
        if current_questions and current_questions > 0:
            return QuizGenerationStatus(task_id=task_id, status="SUCCESS")
        error: str | None = None
        if result.failed():
            error = str(result.result) if result.result is not None else None
        elif isinstance(result.result, dict):
            error = result.result.get("error")
        return QuizGenerationStatus(
            task_id=task_id,
            status="FAILURE",
            error=error or "Quiz generation failed",
        )

    # Still running (or just queued): live detail from the result backend.
    payload = QuizGenerationStatus(task_id=task_id, status=result.status)
    if result.state == "PROGRESS":
        info = result.info or {}
        payload.step = info.get("step")
        payload.done = info.get("done")
        payload.total = info.get("total")
    return payload


@router.post(
    "/{lesson_id}/quiz/questions/{question_id}/regenerate",
    response_model=QuizQuestionTeacherRead,
)
@limiter.limit("20/minute")
async def regenerate_question(
    request: Request,
    lesson_id: UUID,
    question_id: UUID,
    payload: QuizRegenerateRequest,
    _verified: User = Depends(require_verified_email),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestionTeacherRead:
    quiz = await _load_lesson_quiz(db, lesson)
    row = await _load_question(db, quiz.id, question_id)
    if row.type.value != "single_choice":
        raise HTTPException(
            status_code=400,
            detail="Per-question regenerate currently supports only single_choice",
        )

    try:
        material = await assemble_material(db, lesson)
    except EmptyMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    num_options = len(row.payload.get("options") or [])
    usage_service.set_usage_context("quiz_regen_question", lesson_id=lesson_id, quiz_id=quiz.id)
    try:
        updated = await llm_service.regenerate_quiz_question(
            material, row.payload, payload.mode, num_options=num_options
        )
    except LLMOutputError as exc:
        logger.warning("quiz_question_regen_llm_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"LLM returned invalid output: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    new_row = await supersede_with_new_version(db, row, payload=updated)
    await db.commit()
    await db.refresh(new_row)
    return QuizQuestionTeacherRead.model_validate(new_row)


@router.post(
    "/{lesson_id}/quiz/ai-review",
    response_model=list[QuestionFlag],
)
@limiter.limit("5/minute")
async def ai_review(
    request: Request,
    lesson_id: UUID,
    user: User = Depends(require_verified_email),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuestionFlag]:
    quiz = await _load_lesson_quiz(db, lesson)
    rows_q = await db.execute(
        select(QuizQuestion)
        .where(
            QuizQuestion.quiz_id == quiz.id,
            QuizQuestion.superseded_at.is_(None),
        )
        .order_by(QuizQuestion.order, QuizQuestion.created_at)
    )
    rows = list(rows_q.scalars())
    if not rows:
        return []

    structured: dict[UUID, QuestionFlag] = {}
    open_ended: list[QuizQuestion] = []
    for r in rows:
        if r.type.value in _OPEN_ENDED_TYPES:
            open_ended.append(r)
        else:
            structured[r.id] = QuestionFlag(question_id=r.id, kind="ok", note="")

    open_ended_by_id: dict[UUID, QuestionFlag] = {}
    if open_ended:
        try:
            material = await assemble_material(db, lesson)
        except EmptyMaterialError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        # Charged only when the LLM is actually called (structured-only quizzes
        # are reviewed deterministically for free). No trial — credits only.
        amount = CREDIT_WEIGHTS["ai_review"]
        billing_ref = f"ai-review:{quiz.id}:{uuid4().hex[:12]}"
        if not await billing_service.reserve_credits(
            db, user.id, amount, billing_ref, CreditOperation.AI_REVIEW
        ):
            balance = await billing_service.get_balance(db, user.id)
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "insufficient_credits",
                    "required": amount,
                    "available": balance["available"],
                },
            )

        payload = [
            {"id": r.id, "type": r.type.value, "payload": r.payload}
            for r in open_ended
        ]
        usage_service.set_usage_context("ai_review", lesson_id=lesson_id, quiz_id=quiz.id)
        try:
            llm_flags = await llm_service.qa_review_quiz(material, payload)
        except LLMOutputError as exc:
            await billing_service.release_credits(db, user.id, amount, billing_ref)
            logger.warning("quiz_qa_review_llm_error", error=str(exc))
            raise HTTPException(status_code=502, detail=f"LLM returned invalid output: {exc}")
        except Exception:
            await billing_service.release_credits(db, user.id, amount, billing_ref)
            raise
        await billing_service.charge_credits(
            db, user.id, amount, billing_ref, CreditOperation.AI_REVIEW
        )
        open_ended_by_id = {f.question_id: f for f in llm_flags}

    return [structured.get(r.id) or open_ended_by_id[r.id] for r in rows]


# ── Attempts (teacher review + manual override) ─────────────────────────────


@router.get(
    "/{lesson_id}/quiz/attempts",
    response_model=list[QuizAttemptTeacherRead],
)
async def list_attempts(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuizAttemptTeacherRead]:
    quiz = await _load_lesson_quiz(db, lesson)
    rows = await db.execute(
        select(QuizAttempt, User)
        .join(User, User.id == QuizAttempt.student_id)
        .where(QuizAttempt.quiz_id == quiz.id)
        .order_by(desc(QuizAttempt.started_at))
    )
    out: list[QuizAttemptTeacherRead] = []
    for attempt, student in rows.all():
        needs_review_count = await db.scalar(
            select(func.count(QuizAnswer.id))
            .where(QuizAnswer.attempt_id == attempt.id, QuizAnswer.needs_review.is_(True))
        ) or 0
        out.append(
            QuizAttemptTeacherRead(
                id=attempt.id,
                quiz_id=attempt.quiz_id,
                student_id=student.id,
                student_email=student.email,
                student_full_name=student.full_name,
                attempt_number=attempt.attempt_number,
                status=attempt.status,
                score=attempt.score,
                passed=attempt.passed,
                submitted_at=attempt.submitted_at,
                graded_at=attempt.graded_at,
                has_pending_review=needs_review_count > 0,
            )
        )
    return out


@router.get(
    "/{lesson_id}/quiz/attempts/{attempt_id}",
    response_model=QuizAttemptTeacherDetail,
)
async def get_attempt_detail(
    lesson_id: UUID,
    attempt_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizAttemptTeacherDetail:
    quiz = await _load_lesson_quiz(db, lesson)
    attempt = await db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.id == attempt_id, QuizAttempt.quiz_id == quiz.id)
        .options(selectinload(QuizAttempt.answers))
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    student = await db.scalar(select(User).where(User.id == attempt.student_id))
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    try:
        resolved = await resolve_snapshot(db, attempt.questions_snapshot)
    except BrokenSnapshotError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    snap_idx = resolved_index(resolved)
    answers = [
        {
            "id": a.id,
            "question_id": a.question_id,
            "question_payload": (
                snap_idx[a.question_id].payload if a.question_id in snap_idx else {}
            ),
            "response": a.response,
            "awarded_score": a.awarded_score,
            "max_score": a.max_score,
            "is_correct": a.is_correct,
            "needs_review": a.needs_review,
            "llm_feedback": a.llm_feedback,
            "manually_overridden": a.manually_overridden,
            "graded_by_ai": a.graded_by_ai,
        }
        for a in attempt.answers
    ]
    needs_review_count = sum(1 for a in attempt.answers if a.needs_review)

    return QuizAttemptTeacherDetail(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        student_id=student.id,
        student_email=student.email,
        student_full_name=student.full_name,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        score=attempt.score,
        passed=attempt.passed,
        submitted_at=attempt.submitted_at,
        graded_at=attempt.graded_at,
        has_pending_review=needs_review_count > 0,
        ai_graded=any(a.graded_by_ai for a in attempt.answers),
        answers=answers,  # type: ignore[arg-type]
    )


@router.patch(
    "/{lesson_id}/quiz/attempts/{attempt_id}/answers/{answer_id}",
    response_model=QuizAttemptTeacherDetail,
)
async def override_answer_score(
    lesson_id: UUID,
    attempt_id: UUID,
    answer_id: UUID,
    data: AnswerOverride,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizAttemptTeacherDetail:
    quiz = await _load_lesson_quiz(db, lesson)
    attempt = await db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.id == attempt_id, QuizAttempt.quiz_id == quiz.id)
        .options(selectinload(QuizAttempt.answers))
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    answer = next((a for a in attempt.answers if a.id == answer_id), None)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    if data.awarded_score > answer.max_score:
        raise HTTPException(
            status_code=422,
            detail=f"awarded_score must be <= max_score ({answer.max_score})",
        )

    answer.awarded_score = data.awarded_score
    answer.is_correct = bool(data.awarded_score >= answer.max_score)
    answer.needs_review = False
    answer.manually_overridden = True
    answer.graded_by_ai = False
    if data.feedback is not None:
        answer.llm_feedback = data.feedback

    # Atomic recompute: re-aggregate attempt score from current answers using
    # the snapshot's weights (pinned at attempt start), then persist with the
    # override in one transaction.
    try:
        resolved = await resolve_snapshot(db, attempt.questions_snapshot)
    except BrokenSnapshotError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    snap_idx = resolved_index(resolved)
    items: list[tuple[Decimal, Decimal, Decimal]] = []
    for a in attempt.answers:
        q = snap_idx.get(a.question_id)
        if q is None:
            continue
        weight = q.weight if q.weight is not None else Decimal(str(QUIZ_DEFAULT_WEIGHT))
        awarded = a.awarded_score if a.awarded_score is not None else Decimal("0")
        items.append((weight, awarded, a.max_score))
    agg = aggregate_score(items, quiz.pass_threshold)
    attempt.score = agg.score
    attempt.passed = agg.passed
    # Once all answers are accounted for, status moves to graded.
    if not any(a.needs_review for a in attempt.answers):
        attempt.status = AttemptStatus.graded

    await db.commit()
    return await get_attempt_detail(lesson_id, attempt_id, lesson, db)


# ── Manual student grade override ────────────────────────────────────────────


@router.patch(
    "/{lesson_id}/student/{student_id}/grade",
    response_model=GradeOverrideResponse,
)
async def set_student_grade(
    lesson_id: UUID,
    student_id: UUID,
    body: GradeOverride,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> GradeOverrideResponse:
    module = await db.get(Module, lesson.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")

    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == module.course_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Student not enrolled in this course")

    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    threshold = float(quiz.pass_threshold) if quiz else QUIZ_PASS_THRESHOLD

    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if progress is None:
        progress = LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson_id)
        db.add(progress)

    passed = body.score >= threshold
    progress.manual_override_score = body.score
    # Teacher override is authoritative: always recalculate completion by threshold.
    progress.is_completed = passed
    if passed:
        progress.completed_at = progress.completed_at or datetime.now(timezone.utc)
    else:
        progress.completed_at = None

    await db.commit()
    await db.refresh(progress)
    return GradeOverrideResponse(
        lesson_id=lesson_id,
        student_id=student_id,
        manual_override_score=progress.manual_override_score,
        is_completed=progress.is_completed,
    )
