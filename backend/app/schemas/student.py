"""Read DTOs for the student personal cabinet (dashboard + list pages).

All score fields are exposed as 0..100 percentages (the DB stores quiz/assignment
scores normalized 0..1); `None` means "not graded / no data yet".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NearestDeadlineRead(BaseModel):
    assignment_id: UUID
    title: str
    course_title: str
    due_at: datetime


class StudentDashboardRead(BaseModel):
    enrolled_courses: int
    completed_assignments: int
    average_score: float | None
    nearest_deadline: NearestDeadlineRead | None


class StudentQuizRead(BaseModel):
    lesson_id: UUID
    course_id: UUID
    title: str
    course_title: str
    best_score: float | None
    is_passed: bool
    attempts_allowed: int | None


class StudentResultRead(BaseModel):
    attempt_id: UUID
    lesson_id: UUID
    course_id: UUID
    title: str
    course_title: str
    date: datetime
    score: float | None
    passed: bool | None
    status: str


class StudentAssignmentRead(BaseModel):
    assignment_id: UUID
    lesson_id: UUID
    course_id: UUID
    title: str
    course_title: str
    due_at: datetime | None
    max_points: float
    submission_status: str | None
    score: float | None
