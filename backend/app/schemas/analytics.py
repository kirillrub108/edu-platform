from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuizLessonSort(str, enum.Enum):
    last_attempt_at = "last_attempt_at"
    attempts_count = "attempts_count"
    avg_score = "avg_score"
    pass_rate = "pass_rate"
    lesson_title = "lesson_title"


class SortOrder(str, enum.Enum):
    asc = "asc"
    desc = "desc"


class QuizLessonStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lesson_id: UUID
    lesson_title: str
    course_id: UUID
    course_title: str
    module_title: str
    attempts_count: int
    students_count: int
    avg_score: float | None
    pass_rate: float | None
    last_attempt_at: datetime | None


class QuizLessonStatsPage(BaseModel):
    items: list[QuizLessonStats]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class QuizSubmission(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    student_id: UUID
    student_email: str
    student_full_name: str | None
    lesson_id: UUID
    lesson_title: str
    course_title: str
    score: float | None
    is_completed: bool
    completed_at: datetime | None
    passed: bool


class QuizSubmissionPage(BaseModel):
    items: list[QuizSubmission]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class QuizAnalyticsSummary(BaseModel):
    total_quiz_lessons: int
    total_attempts: int
    avg_score: float | None
    pass_rate: float | None
    recent_submissions: list[QuizSubmission]
