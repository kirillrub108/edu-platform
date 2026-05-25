import logging
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.constants import QUIZ_NUM_OPTIONS, QUIZ_NUM_QUESTIONS
from app.database import get_db
from app.dependencies import get_owned_lesson
from app.models.lesson import Lesson, QuizQuestion
from app.schemas.quiz import (
    GeneratedQuestion,
    QuestionFlag,
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizGenerationStatus,
    QuizQuestionRead,
    QuizQuestionUpdate,
    QuizRegenerateRequest,
)
from app.services.llm_service import LLMOutputError, llm_service
from app.services.quiz_service import EmptyMaterialError, assemble_material
from app.tasks.quiz_pipeline import generate_quiz_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/lessons", tags=["quiz-teacher"])


async def _load_question(
    db: AsyncSession, lesson_id: UUID, question_id: UUID
) -> QuizQuestion:
    row = await db.get(QuizQuestion, question_id)
    if row is None or row.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="Quiz question not found")
    return row


@router.post(
    "/{lesson_id}/quiz/generate",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_quiz(
    lesson_id: UUID,
    payload: QuizGenerateRequest,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizGenerateResponse:
    num_questions = payload.num_questions or QUIZ_NUM_QUESTIONS
    num_options = payload.num_options or QUIZ_NUM_OPTIONS

    # Fail fast on empty material so the teacher doesn't have to poll a doomed task.
    try:
        await assemble_material(db, lesson)
    except EmptyMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    task = generate_quiz_task.apply_async(
        args=[str(lesson.id), num_questions, num_options], queue="vision"
    )
    lesson.quiz_task_id = task.id
    await db.commit()
    return QuizGenerateResponse(task_id=task.id, lesson_id=lesson.id)


@router.get(
    "/{lesson_id}/quiz/generation-status/{task_id}",
    response_model=QuizGenerationStatus,
)
async def quiz_generation_status(
    lesson_id: UUID,
    task_id: str,
    _lesson: Lesson = Depends(get_owned_lesson),
) -> QuizGenerationStatus:
    result = AsyncResult(task_id, app=celery_app)
    payload = QuizGenerationStatus(task_id=task_id, status=result.status)
    if result.state == "PROGRESS":
        info = result.info or {}
        payload.step = info.get("step")
        payload.done = info.get("done")
        payload.total = info.get("total")
    elif result.ready():
        if result.failed():
            payload.error = (
                str(result.result) if result.result is not None else "Quiz generation failed"
            )
        elif isinstance(result.result, dict):
            err = result.result.get("error")
            if err:
                payload.error = err
    return payload


@router.get("/{lesson_id}/quiz", response_model=list[QuizQuestionRead])
async def list_quiz_questions(
    lesson_id: UUID,
    _lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuizQuestionRead]:
    rows = await db.execute(
        select(QuizQuestion)
        .where(QuizQuestion.lesson_id == lesson_id)
        .order_by(QuizQuestion.order, QuizQuestion.created_at)
    )
    return [QuizQuestionRead.model_validate(r) for r in rows.scalars()]


@router.patch(
    "/{lesson_id}/quiz/{question_id}",
    response_model=QuizQuestionRead,
)
async def update_quiz_question(
    lesson_id: UUID,
    question_id: UUID,
    data: QuizQuestionUpdate,
    _lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestionRead:
    row = await _load_question(db, lesson_id, question_id)

    updates = data.model_dump(exclude_unset=True)
    next_options = updates.get("options", row.options)
    next_correct = updates.get("correct_index", row.correct_index)
    if not isinstance(next_options, list) or not next_options:
        raise HTTPException(status_code=422, detail="options must be a non-empty list")
    if not 0 <= next_correct < len(next_options):
        raise HTTPException(
            status_code=422,
            detail=f"correct_index {next_correct} out of range for {len(next_options)} options",
        )

    if "question" in updates:
        row.question = updates["question"]
    if "options" in updates:
        row.options = list(updates["options"])
    if "correct_index" in updates:
        row.correct_index = updates["correct_index"]
    if "order" in updates:
        row.order = updates["order"]

    await db.commit()
    await db.refresh(row)
    return QuizQuestionRead.model_validate(row)


@router.post(
    "/{lesson_id}/quiz/{question_id}/regenerate",
    response_model=QuizQuestionRead,
)
async def regenerate_quiz_question(
    lesson_id: UUID,
    question_id: UUID,
    payload: QuizRegenerateRequest,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestionRead:
    row = await _load_question(db, lesson_id, question_id)

    try:
        material = await assemble_material(db, lesson)
    except EmptyMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    current = GeneratedQuestion(
        question=row.question,
        options=list(row.options),
        correct_index=row.correct_index,
    )
    try:
        updated = await llm_service.regenerate_quiz_question(
            material, current, payload.mode, num_options=len(row.options)
        )
    except LLMOutputError as exc:
        logger.warning("regenerate_quiz_question LLM error: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM returned invalid output: {exc}")

    row.question = updated.question
    row.options = list(updated.options)
    row.correct_index = updated.correct_index
    await db.commit()
    await db.refresh(row)
    return QuizQuestionRead.model_validate(row)


@router.post(
    "/{lesson_id}/quiz/qa-review",
    response_model=list[QuestionFlag],
)
async def qa_review(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[QuestionFlag]:
    rows_q = await db.execute(
        select(QuizQuestion)
        .where(QuizQuestion.lesson_id == lesson_id)
        .order_by(QuizQuestion.order, QuizQuestion.created_at)
    )
    rows = list(rows_q.scalars())
    if not rows:
        return []

    try:
        material = await assemble_material(db, lesson)
    except EmptyMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    payload = [
        {
            "id": r.id,
            "question": r.question,
            "options": list(r.options),
            "correct_index": r.correct_index,
        }
        for r in rows
    ]
    try:
        return await llm_service.qa_review_quiz(material, payload)
    except LLMOutputError as exc:
        logger.warning("qa_review_quiz LLM error: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM returned invalid output: {exc}")


@router.delete(
    "/{lesson_id}/quiz/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_quiz_question(
    lesson_id: UUID,
    question_id: UUID,
    _lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _load_question(db, lesson_id, question_id)
    await db.delete(row)
    await db.commit()
