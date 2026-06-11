"""Student-side quiz endpoints — start attempt, save progress, submit.

Hard invariant: the student NEVER sees `correct_*` / `reference_answer` /
`rubric` fields. Payloads are stripped via `to_student_payload` server-side
before serialization; we never trust a runtime filter to do this. The single
exception is the post-submit result when `show_answers && attempts_allowed == 1`
— in that case we include the snapshot's full payload as `correct_payload`
on the answer view.
"""
from __future__ import annotations

import structlog
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    GRADING_MAX_ANSWER_CHARS,
    GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY,
)
from app.database import get_db
from app.dependencies import require_student
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
    MyQuizAttemptsResponse,
    QuizAnswerStudentResult,
    QuizAttemptResult,
    QuizAttemptSave,
    QuizAttemptStartResponse,
    QuizAttemptSummary,
    QuizQuestionStudentRead,
    QuizSubmitResponse,
    to_student_payload,
)
from app.services import quota_service
from app.services.grading_service import (
    ResolvedQuestion,
    aggregate_score,
    build_snapshot,
    grade_question,
    is_open_type,
    open_answer_too_long,
    resolved_index,
)
from app.services.quiz_service import BrokenSnapshotError, resolve_snapshot
from app.tasks.quiz_pipeline import grade_attempt_task

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/students/lessons", tags=["quiz-student"])


# ── Shared helpers ──────────────────────────────────────────────────────────


async def _ensure_enrolled(
    db: AsyncSession, student: User, lesson_id: UUID
) -> tuple[Lesson, Enrollment]:
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id))
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = await db.get(Module, lesson.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.course_id == module.course_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=403, detail="Not enrolled")
    return lesson, enrollment


async def _load_published_quiz(db: AsyncSession, lesson: Lesson) -> Quiz:
    quiz = await db.scalar(
        select(Quiz)
        .where(Quiz.lesson_id == lesson.id)
        .options(selectinload(Quiz.questions))
    )
    # Treat draft as nonexistent from the student's POV — same 404 either way
    # so the API doesn't leak quiz existence.
    if quiz is None or quiz.status != QuizStatus.published or not quiz.questions:
        raise HTTPException(status_code=404, detail="Quiz not available")
    return quiz


def _snapshot_questions(quiz: Quiz) -> dict[str, Any]:
    """Build a pointer snapshot of the quiz's CURRENT versions. Payload is
    not copied — grading resolves pointers back to (id, version) rows, which
    are immutable, so the attempt sees exactly the version it pinned even
    after later edits.
    """
    ordered = sorted(quiz.questions, key=lambda q: (q.order, q.created_at))
    return build_snapshot([
        {"id": q.id, "version": q.version, "order": q.order}
        for q in ordered
    ])


def _student_questions_from_resolved(
    resolved: list[ResolvedQuestion],
) -> list[QuizQuestionStudentRead]:
    return [
        QuizQuestionStudentRead(
            id=q.id,
            type=q.type,
            payload=to_student_payload(q.payload),
            order=q.order,
        )
        for q in resolved
    ]


async def _resolve_or_500(
    db: AsyncSession, snapshot: dict[str, Any]
) -> list[ResolvedQuestion]:
    try:
        return await resolve_snapshot(db, snapshot)
    except BrokenSnapshotError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


async def _build_result(
    db: AsyncSession,
    attempt: QuizAttempt,
    quiz: Quiz,
) -> QuizAttemptResult:
    resolved = await _resolve_or_500(db, attempt.questions_snapshot)
    snap_questions = _student_questions_from_resolved(resolved)
    snap_idx = resolved_index(resolved)

    # Reveal correct payload only when both flags align AND attempt is final.
    reveal_answers = (
        quiz.show_answers
        and quiz.attempts_allowed == 1
        and attempt.status in (AttemptStatus.submitted, AttemptStatus.graded)
    )

    answers_out: list[QuizAnswerStudentResult] = []
    for a in attempt.answers:
        snap_q = snap_idx.get(a.question_id)
        correct_payload = None
        if reveal_answers and snap_q is not None:
            correct_payload = snap_q.payload
        # Open-form feedback is exposed regardless of show_answers (it doesn't
        # reveal the reference answer text — prompt instructs the LLM not to).
        answers_out.append(
            QuizAnswerStudentResult(
                question_id=a.question_id,
                awarded_score=a.awarded_score,
                max_score=a.max_score,
                is_correct=a.is_correct,
                needs_review=a.needs_review,
                llm_feedback=a.llm_feedback,
                correct_payload=correct_payload,
            )
        )
    return QuizAttemptResult(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        score=attempt.score,
        passed=attempt.passed,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
        graded_at=attempt.graded_at,
        grading_task_id=attempt.grading_task_id,
        questions=snap_questions,
        answers=answers_out,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get(
    "/{lesson_id}/quiz-attempts",
    response_model=MyQuizAttemptsResponse,
)
async def get_my_quiz_attempts(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> MyQuizAttemptsResponse:
    lesson, enrollment = await _ensure_enrolled(db, user, lesson_id)

    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson.id))
    if quiz is None:
        return MyQuizAttemptsResponse(
            attempts=[], best_score=None, final_score=None,
            is_manual=False, is_passed=False,
        )

    rows = await db.scalars(
        select(QuizAttempt)
        .where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == user.id,
            QuizAttempt.status.in_([AttemptStatus.submitted, AttemptStatus.graded]),
        )
        .order_by(QuizAttempt.started_at)
    )
    attempts = list(rows.all())

    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )

    best_score = float(progress.quiz_score) if progress and progress.quiz_score is not None else None
    manual = float(progress.manual_override_score) if progress and progress.manual_override_score is not None else None
    final_score = manual if manual is not None else best_score
    is_passed = bool(progress.is_completed) if progress else False

    summaries = [
        QuizAttemptSummary(
            id=a.id,
            attempt_number=a.attempt_number,
            score=float(a.score) if a.score is not None else None,
            passed=a.passed,
            attempted_at=a.submitted_at or a.started_at,
            status=a.status,
        )
        for a in attempts
    ]

    return MyQuizAttemptsResponse(
        attempts=summaries,
        best_score=best_score,
        final_score=final_score,
        is_manual=manual is not None,
        is_passed=is_passed,
    )


@router.get("/{lesson_id}/quiz")
async def get_quiz_for_student(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lesson, _ = await _ensure_enrolled(db, user, lesson_id)
    quiz = await _load_published_quiz(db, lesson)

    # Existing in-progress attempt (resume)?
    in_progress = await db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == user.id,
            QuizAttempt.status == AttemptStatus.in_progress,
        )
        .options(selectinload(QuizAttempt.answers))
        .order_by(desc(QuizAttempt.started_at))
        .limit(1)
    )

    # Attempts already used.
    used = await db.scalar(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == user.id,
        )
    ) or 0

    return {
        "quiz_id": str(quiz.id),
        "pass_threshold": str(quiz.pass_threshold),
        "attempts_allowed": quiz.attempts_allowed,
        "attempts_used": used,
        "show_answers": quiz.show_answers,
        "shuffle": quiz.shuffle,
        "in_progress_attempt_id": str(in_progress.id) if in_progress else None,
    }


@router.post(
    "/{lesson_id}/quiz/attempts",
    response_model=QuizAttemptStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_attempt(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> QuizAttemptStartResponse:
    lesson, _ = await _ensure_enrolled(db, user, lesson_id)
    quiz = await _load_published_quiz(db, lesson)

    # If there's an open attempt, return it instead of starting a new one
    # (no orphans, no accidental double-start from a double-click).
    existing = await db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == user.id,
            QuizAttempt.status == AttemptStatus.in_progress,
        )
        .order_by(desc(QuizAttempt.started_at))
        .limit(1)
    )
    if existing is not None:
        existing_resolved = await _resolve_or_500(db, existing.questions_snapshot)
        return QuizAttemptStartResponse(
            attempt_id=existing.id,
            quiz_id=quiz.id,
            attempt_number=existing.attempt_number,
            started_at=existing.started_at,
            questions=_student_questions_from_resolved(existing_resolved),
        )

    # Enforce attempts_allowed.
    used = await db.scalar(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == user.id,
        )
    ) or 0
    if quiz.attempts_allowed is not None and used >= quiz.attempts_allowed:
        raise HTTPException(status_code=409, detail="No attempts left")

    snapshot = _snapshot_questions(quiz)
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        student_id=user.id,
        attempt_number=used + 1,
        status=AttemptStatus.in_progress,
        questions_snapshot=snapshot,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    resolved = await _resolve_or_500(db, snapshot)
    return QuizAttemptStartResponse(
        attempt_id=attempt.id,
        quiz_id=quiz.id,
        attempt_number=attempt.attempt_number,
        started_at=attempt.started_at,
        questions=_student_questions_from_resolved(resolved),
    )


async def _load_owned_attempt(
    db: AsyncSession, user: User, attempt_id: UUID
) -> QuizAttempt:
    attempt = await db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.id == attempt_id, QuizAttempt.student_id == user.id)
        .options(selectinload(QuizAttempt.answers))
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


@router.put("/{lesson_id}/quiz/attempts/{attempt_id}")
async def save_attempt_progress(
    lesson_id: UUID,
    attempt_id: UUID,
    data: QuizAttemptSave,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    attempt = await _load_owned_attempt(db, user, attempt_id)
    if attempt.status != AttemptStatus.in_progress:
        raise HTTPException(status_code=409, detail="Attempt is no longer in progress")

    # Validate against the pinned pointer set — no DB resolution needed; we
    # only check membership, not payloads.
    from app.services.grading_service import snapshot_pointers
    valid_ids = {
        UUID(str(p["question_id"]))
        for p in snapshot_pointers(attempt.questions_snapshot)
    }
    by_qid = {a.question_id: a for a in attempt.answers}
    for item in data.answers:
        if item.question_id not in valid_ids:
            raise HTTPException(
                status_code=422, detail=f"Unknown question_id: {item.question_id}"
            )
        existing = by_qid.get(item.question_id)
        if existing is None:
            db.add(
                QuizAnswer(
                    attempt_id=attempt.id,
                    question_id=item.question_id,
                    response=item.response,
                    max_score=Decimal("1.0"),
                )
            )
        else:
            existing.response = item.response
    await db.commit()
    return {"status": "saved"}


def _reject_overlong_open_answers(
    attempt: QuizAttempt, snap_idx: dict[UUID, ResolvedQuestion]
) -> None:
    """422 if any open answer exceeds the char cap — before any LLM call."""
    for ans in attempt.answers:
        q = snap_idx.get(ans.question_id)
        if q is None or not is_open_type(q.type):
            continue
        text = str(ans.response.get("text", "")) if ans.response else ""
        if open_answer_too_long(text):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "answer_too_long",
                    "limit": GRADING_MAX_ANSWER_CHARS,
                    "length": len(text),
                },
            )


async def _reserve_grading_slot(
    db: AsyncSession, student_id: UUID, quiz_id: UUID
) -> None:
    """Atomically take one daily grading slot for (student, quiz); 429 when the
    day's cap is exhausted. A failed reservation is not refunded — a downstream
    LLM failure must not hand the slot back (anti-abuse)."""
    resource = quota_service.grading_resource(quiz_id)
    period = quota_service.utc_day_key()
    allowed = await quota_service.try_consume_slot(
        db, student_id, resource, GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY, period
    )
    if not allowed:
        used = await quota_service.get_usage(db, student_id, resource, period)
        raise HTTPException(
            status_code=429,
            detail={
                "code": "grading_rate_limited",
                "limit": GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY,
                "used": used,
            },
        )


@router.post(
    "/{lesson_id}/quiz/attempts/{attempt_id}/submit",
    response_model=QuizSubmitResponse,
)
async def submit_attempt(
    lesson_id: UUID,
    attempt_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> QuizSubmitResponse:
    attempt = await _load_owned_attempt(db, user, attempt_id)
    if attempt.status != AttemptStatus.in_progress:
        raise HTTPException(status_code=409, detail="Attempt already submitted")

    resolved = await _resolve_or_500(db, attempt.questions_snapshot)
    snap_idx = resolved_index(resolved)
    by_qid = {a.question_id: a for a in attempt.answers}
    needs_open_grading = False

    # Anti-abuse gates for the free open-answer LLM grading (students only,
    # teachers never reach here). Both run before any mutation or LLM enqueue,
    # and only when the attempt actually has open questions — purely closed
    # submits are never metered and behave exactly as before.
    if any(is_open_type(q.type) for q in resolved):
        _reject_overlong_open_answers(attempt, snap_idx)
        await _reserve_grading_slot(db, user.id, attempt.quiz_id)

    # 1. Ensure a QuizAnswer row exists for every snapshot question.
    for qid in snap_idx:
        if qid not in by_qid:
            ans = QuizAnswer(
                attempt_id=attempt.id,
                question_id=qid,
                response={},
                max_score=Decimal("1.0"),
            )
            db.add(ans)
            by_qid[qid] = ans
    await db.flush()

    # 2. Deterministic grading for closed types (open → needs_review=True).
    for qid, ans in by_qid.items():
        snap_q = snap_idx[qid]
        outcome = grade_question(snap_q.type, snap_q.payload, ans.response or {})
        ans.max_score = outcome.max_score
        if is_open_type(snap_q.type):
            # Don't fix awarded_score yet — wait for LLM/teacher.
            ans.needs_review = True
            ans.is_correct = None
            ans.awarded_score = None
            needs_open_grading = True
        else:
            ans.awarded_score = outcome.awarded_score
            ans.is_correct = outcome.is_correct
            ans.needs_review = False

    quiz = await db.get(Quiz, attempt.quiz_id)
    assert quiz is not None

    # 3. Provisional aggregate (open answers count as 0 for now). If no open
    #    answers, this IS the final score and we mark graded immediately.
    items: list[tuple[Decimal, Decimal, Decimal]] = []
    for qid, ans in by_qid.items():
        weight = snap_idx[qid].weight
        awarded = ans.awarded_score if ans.awarded_score is not None else Decimal("0")
        items.append((weight, awarded, ans.max_score))
    agg = aggregate_score(items, quiz.pass_threshold)
    attempt.score = agg.score
    attempt.passed = agg.passed
    attempt.submitted_at = datetime.now(timezone.utc)

    grading_task_id: str | None = None
    if needs_open_grading:
        attempt.status = AttemptStatus.submitted
        await db.commit()
        task = grade_attempt_task.apply_async(args=[str(attempt.id)], queue="quiz")
        attempt.grading_task_id = task.id
        await db.commit()
        grading_task_id = task.id
    else:
        attempt.status = AttemptStatus.graded
        attempt.graded_at = attempt.submitted_at
        # Sync the lesson-progress side-effect (passed → completed).
        await _mark_progress_passed(db, user, lesson_id, attempt)
        await db.commit()

    return QuizSubmitResponse(
        attempt_id=attempt.id,
        status=attempt.status,
        score=attempt.score,
        passed=attempt.passed,
        grading_task_id=grading_task_id,
    )


async def _mark_progress_passed(
    db: AsyncSession,
    user: User,
    lesson_id: UUID,
    attempt: QuizAttempt,
) -> None:
    """Mirror tasks.quiz_pipeline._mark_lesson_progress_if_passed for the
    no-open-answers fast path (graded synchronously inside submit)."""
    if not attempt.passed:
        return
    lesson, enrollment = await _ensure_enrolled(db, user, lesson_id)
    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    if progress is None:
        progress = LessonProgress(
            enrollment_id=enrollment.id, lesson_id=lesson.id
        )
        db.add(progress)
    new_score = float(attempt.score) if attempt.score is not None else 0.0
    if progress.quiz_score is None or new_score > progress.quiz_score:
        progress.quiz_score = new_score
    if not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = datetime.now(timezone.utc)


@router.get(
    "/{lesson_id}/quiz/attempts/{attempt_id}",
    response_model=QuizAttemptResult,
)
async def get_attempt(
    lesson_id: UUID,
    attempt_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> QuizAttemptResult:
    attempt = await _load_owned_attempt(db, user, attempt_id)
    quiz = await db.get(Quiz, attempt.quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return await _build_result(db, attempt, quiz)
