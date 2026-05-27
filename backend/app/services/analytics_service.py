from __future__ import annotations

from uuid import UUID

from sqlalchemy import Float, and_, case, cast, desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import QUIZ_PASS_THRESHOLD
from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.quiz import AttemptStatus, Quiz, QuizAttempt
from app.models.user import User
from app.schemas.analytics import (
    QuizAnalyticsSummary,
    QuizLessonSort,
    QuizLessonStats,
    QuizLessonStatsPage,
    QuizSubmission,
    QuizSubmissionPage,
    SortOrder,
)


# ── Source of truth ─────────────────────────────────────────────────────────
# Analytics aggregates QuizAttempt directly. LessonProgress is *only* written
# for attempts that passed (_mark_progress_passed), so it would invisibly drop
# every failed attempt from the report. A lesson appears in analytics when it
# has at least one related Quiz (regardless of Lesson.content_type — the UI
# lets video/text lessons carry a quiz tab too).
#
# Per (student, quiz) we collapse multiple attempts into the BEST graded one
# (max score) using a window function. Only attempts with status=graded and
# score IS NOT NULL count toward aggregates.


def _best_attempts_cte():
    """Pick the best graded attempt per (quiz_id, student_id)."""
    row_number = func.row_number().over(
        partition_by=(QuizAttempt.quiz_id, QuizAttempt.student_id),
        order_by=(desc(QuizAttempt.score), desc(QuizAttempt.submitted_at)),
    ).label("rn")
    subq = (
        select(
            QuizAttempt.id.label("attempt_id"),
            QuizAttempt.quiz_id.label("quiz_id"),
            QuizAttempt.student_id.label("student_id"),
            QuizAttempt.score.label("score"),
            QuizAttempt.passed.label("passed"),
            QuizAttempt.submitted_at.label("submitted_at"),
            row_number,
        )
        .where(QuizAttempt.status == AttemptStatus.graded)
        .where(QuizAttempt.score.is_not(None))
        .subquery()
    )
    return subq


def _quiz_lessons_subquery(owner_id: UUID):
    """Lessons owned by the teacher that have a Quiz attached."""
    return (
        select(
            Lesson.id.label("lesson_id"),
            Lesson.title.label("lesson_title"),
            Module.title.label("module_title"),
            Module.course_id.label("course_id"),
            Course.title.label("course_title"),
            Quiz.id.label("quiz_id"),
        )
        .select_from(Lesson)
        .join(Quiz, Quiz.lesson_id == Lesson.id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(Course.owner_id == owner_id)
        .subquery()
    )


async def get_summary(db: AsyncSession, owner_id: UUID) -> QuizAnalyticsSummary:
    quiz_lessons = _quiz_lessons_subquery(owner_id)
    best = _best_attempts_cte()

    # Totals: every graded attempt across this teacher's quizzes.
    totals_stmt = (
        select(
            func.count(func.distinct(quiz_lessons.c.lesson_id)).label("lessons"),
            func.count(QuizAttempt.id).label("attempts"),
            func.avg(cast(QuizAttempt.score, Float)).label("avg_score"),
            func.avg(
                cast(
                    case(
                        (QuizAttempt.score.is_(None), None),
                        (QuizAttempt.score >= QUIZ_PASS_THRESHOLD, 1.0),
                        else_=0.0,
                    ),
                    Float,
                )
            ).label("pass_rate"),
        )
        .select_from(quiz_lessons)
        .outerjoin(
            QuizAttempt,
            and_(
                QuizAttempt.quiz_id == quiz_lessons.c.quiz_id,
                QuizAttempt.status == AttemptStatus.graded,
                QuizAttempt.score.is_not(None),
            ),
        )
    )
    row = (await db.execute(totals_stmt)).one()

    # Recent submissions = most recent graded attempts (10), one row per
    # (student, lesson) — best score for that pair.
    recent_stmt = (
        select(
            User.id.label("student_id"),
            User.email.label("student_email"),
            User.full_name.label("student_full_name"),
            quiz_lessons.c.lesson_id.label("lesson_id"),
            quiz_lessons.c.lesson_title.label("lesson_title"),
            quiz_lessons.c.course_title.label("course_title"),
            best.c.score.label("score"),
            best.c.submitted_at.label("submitted_at"),
        )
        .select_from(best)
        .join(quiz_lessons, quiz_lessons.c.quiz_id == best.c.quiz_id)
        .join(User, User.id == best.c.student_id)
        .where(best.c.rn == 1)
        .order_by(desc(best.c.submitted_at))
        .limit(10)
    )
    recent_rows = (await db.execute(recent_stmt)).all()
    recent = [
        QuizSubmission(
            student_id=r.student_id,
            student_email=r.student_email,
            student_full_name=r.student_full_name,
            lesson_id=r.lesson_id,
            lesson_title=r.lesson_title,
            course_title=r.course_title,
            score=float(r.score) if r.score is not None else None,
            is_completed=r.score is not None and float(r.score) >= QUIZ_PASS_THRESHOLD,
            completed_at=r.submitted_at,
            passed=r.score is not None and float(r.score) >= QUIZ_PASS_THRESHOLD,
        )
        for r in recent_rows
    ]

    return QuizAnalyticsSummary(
        total_quiz_lessons=int(row.lessons or 0),
        total_attempts=int(row.attempts or 0),
        avg_score=float(row.avg_score) if row.avg_score is not None else None,
        pass_rate=float(row.pass_rate) if row.pass_rate is not None else None,
        recent_submissions=recent,
    )


def _sort_column(sort: QuizLessonSort):
    if sort is QuizLessonSort.lesson_title:
        return Lesson.title
    if sort is QuizLessonSort.attempts_count:
        return func.count(QuizAttempt.id)
    if sort is QuizLessonSort.avg_score:
        return func.avg(cast(QuizAttempt.score, Float))
    if sort is QuizLessonSort.pass_rate:
        return func.avg(
            cast(
                case(
                    (QuizAttempt.score.is_(None), None),
                    (QuizAttempt.score >= QUIZ_PASS_THRESHOLD, 1.0),
                    else_=0.0,
                ),
                Float,
            )
        )
    return func.max(QuizAttempt.submitted_at)  # last_attempt_at


async def list_quiz_lessons(
    db: AsyncSession,
    owner_id: UUID,
    *,
    course_id: UUID | None,
    search: str | None,
    sort: QuizLessonSort,
    order: SortOrder,
    page: int,
    page_size: int,
) -> QuizLessonStatsPage:
    base = (
        select(Lesson.id)
        .join(Quiz, Quiz.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(Course.owner_id == owner_id)
    )
    if course_id is not None:
        base = base.where(Course.id == course_id)
    if search:
        base = base.where(Lesson.title.ilike(f"%{search}%"))

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    attempts_col = func.count(QuizAttempt.id).label("attempts_count")
    students_col = func.count(func.distinct(QuizAttempt.student_id)).label(
        "students_count"
    )
    avg_col = func.avg(cast(QuizAttempt.score, Float)).label("avg_score")
    pass_col = func.avg(
        cast(
            case(
                (QuizAttempt.score.is_(None), None),
                (QuizAttempt.score >= QUIZ_PASS_THRESHOLD, 1.0),
                else_=0.0,
            ),
            Float,
        )
    ).label("pass_rate")
    last_col = func.max(QuizAttempt.submitted_at).label("last_attempt_at")

    stmt = (
        select(
            Lesson.id.label("lesson_id"),
            Lesson.title.label("lesson_title"),
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Module.title.label("module_title"),
            attempts_col,
            students_col,
            avg_col,
            pass_col,
            last_col,
        )
        .select_from(Lesson)
        .join(Quiz, Quiz.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        # Outer join keeps quizzes with zero graded attempts in the result.
        .outerjoin(
            QuizAttempt,
            and_(
                QuizAttempt.quiz_id == Quiz.id,
                QuizAttempt.status == AttemptStatus.graded,
                QuizAttempt.score.is_not(None),
            ),
        )
        .where(Course.owner_id == owner_id)
        .group_by(Lesson.id, Lesson.title, Course.id, Course.title, Module.title)
    )
    if course_id is not None:
        stmt = stmt.where(Course.id == course_id)
    if search:
        stmt = stmt.where(Lesson.title.ilike(f"%{search}%"))

    sort_expr = _sort_column(sort)
    if order is SortOrder.asc:
        stmt = stmt.order_by(sort_expr.asc().nullslast(), Lesson.title.asc())
    else:
        stmt = stmt.order_by(sort_expr.desc().nullslast(), Lesson.title.asc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).all()
    items = [
        QuizLessonStats(
            lesson_id=r.lesson_id,
            lesson_title=r.lesson_title,
            course_id=r.course_id,
            course_title=r.course_title,
            module_title=r.module_title,
            attempts_count=int(r.attempts_count or 0),
            students_count=int(r.students_count or 0),
            avg_score=float(r.avg_score) if r.avg_score is not None else None,
            pass_rate=float(r.pass_rate) if r.pass_rate is not None else None,
            last_attempt_at=r.last_attempt_at,
        )
        for r in rows
    ]
    return QuizLessonStatsPage(
        items=items, total=int(total), page=page, page_size=page_size
    )


class LessonNotOwnedOrNoQuiz(Exception):
    """Lesson missing, owned by another teacher, or has no quiz attached."""


async def get_lesson_submissions(
    db: AsyncSession,
    owner_id: UUID,
    *,
    lesson_id: UUID,
    page: int,
    page_size: int,
) -> QuizSubmissionPage:
    lesson_row = (
        await db.execute(
            select(Lesson.id, Lesson.title, Course.title, Quiz.id)
            .join(Module, Lesson.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .join(Quiz, Quiz.lesson_id == Lesson.id)
            .where(Lesson.id == lesson_id)
            .where(Course.owner_id == owner_id)
        )
    ).first()
    if lesson_row is None:
        raise LessonNotOwnedOrNoQuiz()

    lesson_title = lesson_row[1]
    course_title = lesson_row[2]
    quiz_id = lesson_row[3]

    best = _best_attempts_cte()

    base = (
        select(best.c.attempt_id)
        .where(best.c.quiz_id == quiz_id)
        .where(best.c.rn == 1)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    stmt = (
        select(
            User.id.label("student_id"),
            User.email.label("student_email"),
            User.full_name.label("student_full_name"),
            best.c.score.label("score"),
            best.c.submitted_at.label("submitted_at"),
        )
        .select_from(best)
        .join(User, User.id == best.c.student_id)
        .where(best.c.quiz_id == quiz_id)
        .where(best.c.rn == 1)
        .order_by(desc(best.c.submitted_at), User.email.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        QuizSubmission(
            student_id=r.student_id,
            student_email=r.student_email,
            student_full_name=r.student_full_name,
            lesson_id=lesson_id,
            lesson_title=lesson_title,
            course_title=course_title,
            score=float(r.score) if r.score is not None else None,
            is_completed=r.score is not None and float(r.score) >= QUIZ_PASS_THRESHOLD,
            completed_at=r.submitted_at,
            passed=r.score is not None and float(r.score) >= QUIZ_PASS_THRESHOLD,
        )
        for r in rows
    ]
    return QuizSubmissionPage(
        items=items, total=int(total), page=page, page_size=page_size
    )
