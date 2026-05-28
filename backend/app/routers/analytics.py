from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_teacher
from app.models.user import User
from app.schemas.analytics import (
    QuizAnalyticsSummary,
    QuizLessonSort,
    QuizLessonStatsPage,
    QuizResultOut,
    QuizResultPatch,
    QuizResultsResponse,
    QuizSubmissionPage,
    SortOrder,
)
from app.services import analytics_service
from app.services.analytics_service import LessonNotOwnedByTeacher, LessonNotOwnedOrNoQuiz

router = APIRouter(prefix="/api/v1/teacher/analytics", tags=["analytics"])
lesson_results_router = APIRouter(prefix="/api/v1/teacher/lessons", tags=["analytics"])


@router.get("/summary", response_model=QuizAnalyticsSummary)
async def quiz_analytics_summary(
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> QuizAnalyticsSummary:
    return await analytics_service.get_summary(db, user.id)


@router.get("/quiz-lessons", response_model=QuizLessonStatsPage)
async def quiz_lessons(
    course_id: UUID | None = None,
    search: str | None = None,
    sort: QuizLessonSort = QuizLessonSort.last_attempt_at,
    order: SortOrder = SortOrder.desc,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> QuizLessonStatsPage:
    return await analytics_service.list_quiz_lessons(
        db,
        user.id,
        course_id=course_id,
        search=search.strip() if search else None,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/quiz-lessons/{lesson_id}/submissions",
    response_model=QuizSubmissionPage,
)
async def lesson_submissions(
    lesson_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> QuizSubmissionPage:
    try:
        return await analytics_service.get_lesson_submissions(
            db, user.id, lesson_id=lesson_id, page=page, page_size=page_size
        )
    except LessonNotOwnedOrNoQuiz:
        raise HTTPException(status_code=404, detail="Quiz lesson not found")


@lesson_results_router.get(
    "/{lesson_id}/quiz-results",
    response_model=QuizResultsResponse,
)
async def get_lesson_quiz_results(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> QuizResultsResponse:
    try:
        return await analytics_service.get_quiz_results(db, user.id, lesson_id)
    except LessonNotOwnedByTeacher:
        raise HTTPException(status_code=404, detail="Lesson not found")


@lesson_results_router.patch(
    "/{lesson_id}/quiz-results/{student_id}",
    response_model=QuizResultOut,
)
async def patch_lesson_quiz_result(
    lesson_id: UUID,
    student_id: UUID,
    body: QuizResultPatch,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> QuizResultOut:
    try:
        return await analytics_service.patch_quiz_result(
            db, user.id, lesson_id, student_id, body.quiz_score, body.reason
        )
    except LessonNotOwnedByTeacher:
        raise HTTPException(status_code=404, detail="Lesson or student not found")
