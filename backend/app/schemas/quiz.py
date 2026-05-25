from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuizQuestionStudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    options: list[str]
    order: int


# ── Teacher authoring schemas ────────────────────────────────────────────────


class GeneratedQuestion(BaseModel):
    """A validated quiz question as produced by the LLM (no DB id yet)."""

    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)


class QuizQuestionRead(BaseModel):
    """Teacher view — includes correct_index."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    question: str
    options: list[str]
    correct_index: int
    order: int
    created_at: datetime
    updated_at: datetime


class QuizQuestionUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1)
    options: list[str] | None = Field(default=None, min_length=2)
    correct_index: int | None = Field(default=None, ge=0)
    order: int | None = Field(default=None, ge=0)


RegenerateMode = Literal["rephrase", "harder", "easier", "improve_distractors"]


class QuizRegenerateRequest(BaseModel):
    mode: RegenerateMode


FlagKind = Literal["ok", "wrong_answer", "ambiguous", "duplicate"]


class QuestionFlag(BaseModel):
    question_id: UUID
    kind: FlagKind
    note: str = ""


class QuizGenerateRequest(BaseModel):
    num_questions: int | None = Field(default=None, ge=1, le=20)
    num_options: int | None = Field(default=None, ge=2, le=8)


class QuizGenerateResponse(BaseModel):
    task_id: str
    lesson_id: UUID


class QuizGenerationStatus(BaseModel):
    task_id: str
    status: str
    step: str | None = None
    done: int | None = None
    total: int | None = None
    error: str | None = None


class QuizAnswerItem(BaseModel):
    question_id: UUID
    selected_index: int = Field(ge=0)


class QuizAnswerSubmit(BaseModel):
    answers: list[QuizAnswerItem]


class QuizQuestionResult(BaseModel):
    question_id: UUID
    correct: bool
    correct_index: int


class QuizResultRead(BaseModel):
    score: float
    correct_count: int
    total: int
    passed: bool
    questions: list[QuizQuestionResult]


class QuizTeacherResultRow(BaseModel):
    student_id: UUID
    full_name: str | None
    email: str
    quiz_score: float | None
    attempted: bool
    completed: bool
