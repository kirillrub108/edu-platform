"""Celery tasks for the quiz domain — both run on the `quiz` queue.

Two distinct workflows:

  * `generate_quiz_task` — LLM-generates polymorphic questions for a Quiz.
    Updates `Quiz.generation_task_id` as the polling handle.

  * `grade_attempt_task` — grades the LLM-flagged open-form answers of a
    submitted attempt in parallel. Closed-form answers were already graded
    deterministically at submit time; this task only fills in short_answer
    / essay scores, then recomputes the attempt-level score.

The thread-pool pattern mirrors `tasks.video_pipeline`: bounded executor +
`as_completed` + per-future progress callback. `asyncio.run` is used inside
worker threads to call the async LLM client.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.constants import QUIZ_GRADING_WORKERS, QUIZ_TYPE_DISTRIBUTION
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson
from app.models.quiz import (
    AttemptStatus,
    Quiz,
    QuizAnswer,
    QuizAttempt,
)
from app.services.grading_service import (
    aggregate_score,
    is_open_type,
    resolved_index,
)
from app.services.llm_service import LLMOutputError, llm_service
from app.services.quiz_service import (
    BrokenSnapshotError,
    EmptyMaterialError,
    assemble_material_sync,
    get_or_create_quiz_sync,
    replace_questions_sync,
    resolve_snapshot_sync,
)
from app.tasks.video_pipeline import SyncSession, _publish

logger = structlog.get_logger()


def _clear_generation_task(session: Session, quiz_id: UUID) -> None:
    quiz = session.get(Quiz, quiz_id)
    if quiz is not None:
        quiz.generation_task_id = None
        session.commit()


@celery_app.task(bind=True, name="generate_quiz", queue="quiz")
def generate_quiz_task(
    self,
    lesson_id: str,
    num_questions: int,
    num_options: int,
    types: list[str] | None = None,
) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    lesson_uuid = UUID(lesson_id)
    allowed_types = list(types) if types else list(QUIZ_TYPE_DISTRIBUTION.keys())

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(state="PROGRESS", meta={"step": step, "done": done, "total": total})
        _publish(lesson_id, {"step": step, "done": done, "total": total})

    with SyncSession() as session:
        try:
            _progress("material", 0, 3)
            material = assemble_material_sync(session, lesson_uuid)
            quiz = get_or_create_quiz_sync(session, lesson_uuid)
            quiz_id = quiz.id

            _progress("llm", 1, 3)
            generated = asyncio.run(
                llm_service.generate_quiz_v2(
                    material,
                    num_questions=num_questions,
                    num_options=num_options,
                    types=allowed_types,
                )
            )

            _progress("persist", 2, 3)
            replace_questions_sync(session, quiz_id, generated)
            _clear_generation_task(session, quiz_id)
            session.commit()
            _progress("persist", 3, 3)
            return {"status": "ok", "total": len(generated), "quiz_id": str(quiz_id)}

        except EmptyMaterialError as exc:
            session.rollback()
            quiz_row = session.query(Quiz).filter(Quiz.lesson_id == lesson_uuid).first()
            if quiz_row:
                _clear_generation_task(session, quiz_row.id)
            logger.warning("quiz_gen_empty_material", lesson_id=lesson_id)
            return {"status": "error", "error": str(exc)}
        except LLMOutputError as exc:
            session.rollback()
            quiz_row = session.query(Quiz).filter(Quiz.lesson_id == lesson_uuid).first()
            if quiz_row:
                _clear_generation_task(session, quiz_row.id)
            logger.error("quiz_gen_llm_invalid", error=str(exc))
            return {"status": "error", "error": str(exc)}
        except Exception as exc:
            session.rollback()
            quiz_row = session.query(Quiz).filter(Quiz.lesson_id == lesson_uuid).first()
            if quiz_row:
                _clear_generation_task(session, quiz_row.id)
            logger.exception("quiz_gen_failed", lesson_id=lesson_id)
            return {"status": "error", "error": str(exc)}


# ── Grading: parallel LLM evaluation of open answers ─────────────────────────


def _grade_one_open(
    answer_id: UUID,
    payload: dict[str, Any],
    response_text: str,
) -> tuple[UUID, float, str, bool]:
    """Run LLM grading for a single open answer. Returns (answer_id, score,
    feedback, ok) — ok=False signals LLM failure (router treats as needs_review).
    """
    try:
        score, feedback = asyncio.run(llm_service.grade_open_answer(payload, response_text))
        return answer_id, score, feedback, True
    except Exception as exc:
        logger.warning("grade_attempt_llm_failed", answer_id=str(answer_id), error=str(exc))
        return answer_id, 0.0, f"Автоматическая проверка не удалась: {exc}", False


def _recompute_attempt(session: Session, attempt: QuizAttempt) -> None:
    """Aggregate per-answer scores into attempt.score / passed using the
    snapshot's weights. Called both after LLM grading and after manual
    override, so the two paths produce identical numbers.
    """
    resolved = resolve_snapshot_sync(session, attempt.questions_snapshot)
    snap_idx = resolved_index(resolved)
    items: list[tuple[Decimal, Decimal, Decimal]] = []
    for ans in attempt.answers:
        q = snap_idx.get(ans.question_id)
        if q is None:
            continue
        awarded = ans.awarded_score if ans.awarded_score is not None else Decimal("0")
        items.append((q.weight, awarded, ans.max_score))

    quiz = session.get(Quiz, attempt.quiz_id)
    threshold = quiz.pass_threshold if quiz else Decimal("0.6")
    agg = aggregate_score(items, threshold)
    attempt.score = agg.score
    attempt.passed = agg.passed


def _mark_lesson_progress_if_passed(session: Session, attempt: QuizAttempt) -> None:
    """If the attempt passed, bump the student's LessonProgress: set
    quiz_score to max(existing, new) and is_completed=True. Best-attempt
    policy: a later worse attempt never regresses a previously passed lesson.
    """
    from app.models.lesson import Module

    if not attempt.passed:
        return
    quiz = session.get(Quiz, attempt.quiz_id)
    if quiz is None:
        return
    lesson = session.get(Lesson, quiz.lesson_id)
    if lesson is None:
        return
    module = session.get(Module, lesson.module_id)
    if module is None:
        return

    enrollment = session.query(Enrollment).filter(
        Enrollment.student_id == attempt.student_id,
        Enrollment.course_id == module.course_id,
    ).first()
    if enrollment is None:
        return

    progress = session.query(LessonProgress).filter(
        LessonProgress.enrollment_id == enrollment.id,
        LessonProgress.lesson_id == quiz.lesson_id,
    ).first()
    if progress is None:
        progress = LessonProgress(
            enrollment_id=enrollment.id,
            lesson_id=quiz.lesson_id,
        )
        session.add(progress)

    new_score = float(attempt.score) if attempt.score is not None else 0.0
    if progress.quiz_score is None or new_score > progress.quiz_score:
        progress.quiz_score = new_score
    if not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = datetime.now(timezone.utc)


@celery_app.task(bind=True, name="grade_attempt", queue="quiz")
def grade_attempt_task(self, attempt_id: str) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    attempt_uuid = UUID(attempt_id)

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(state="PROGRESS", meta={"step": step, "done": done, "total": total})

    with SyncSession() as session:
        try:
            attempt = session.get(QuizAttempt, attempt_uuid)
            if attempt is None:
                return {"status": "error", "error": "attempt not found"}

            try:
                resolved = resolve_snapshot_sync(session, attempt.questions_snapshot)
            except BrokenSnapshotError as exc:
                logger.error("grade_attempt_broken_snapshot", attempt_id=attempt_id, error=str(exc))
                return {"status": "error", "error": str(exc)}
            snap_idx = resolved_index(resolved)
            open_jobs: list[tuple[UUID, dict[str, Any], str]] = []
            for ans in attempt.answers:
                if not ans.needs_review:
                    continue
                q = snap_idx.get(ans.question_id)
                if q is None:
                    continue
                if not is_open_type(q.type):
                    continue
                response_text = str(ans.response.get("text", "")) if ans.response else ""
                open_jobs.append((ans.id, q.payload, response_text))

            total = len(open_jobs)
            _progress("grading", 0, total or 1)

            if open_jobs:
                done = 0
                with ThreadPoolExecutor(
                    max_workers=QUIZ_GRADING_WORKERS, thread_name_prefix="grade"
                ) as pool:
                    futs = {
                        pool.submit(_grade_one_open, ans_id, payload, text): ans_id
                        for ans_id, payload, text in open_jobs
                    }
                    for fut in as_completed(futs):
                        ans_id, score, feedback, ok = fut.result()
                        ans = session.get(QuizAnswer, ans_id)
                        if ans is None:
                            continue
                        if ok:
                            ans.awarded_score = Decimal(str(score))
                            ans.is_correct = score >= 0.999
                            ans.needs_review = False
                            ans.llm_feedback = feedback
                        else:
                            # Keep needs_review=True so the teacher reviews it.
                            ans.llm_feedback = feedback
                        session.flush()
                        done += 1
                        _progress("grading", done, total)

            # Re-load attempt with fresh answers, then aggregate + mark progress.
            session.refresh(attempt)
            _recompute_attempt(session, attempt)
            attempt.status = AttemptStatus.graded
            attempt.graded_at = datetime.now(timezone.utc)
            attempt.grading_task_id = None
            _mark_lesson_progress_if_passed(session, attempt)
            session.commit()

            return {
                "status": "ok",
                "attempt_id": attempt_id,
                "score": float(attempt.score) if attempt.score is not None else None,
                "passed": bool(attempt.passed),
            }

        except Exception as exc:
            session.rollback()
            logger.exception("grade_attempt_failed", attempt_id=attempt_id)
            # Best-effort: clear grading_task_id so the student isn't stuck.
            try:
                a = session.get(QuizAttempt, attempt_uuid)
                if a is not None:
                    a.grading_task_id = None
                    session.commit()
            except Exception:
                pass
            return {"status": "error", "error": str(exc)}
