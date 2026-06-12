from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.course import CourseDetail


class GradebookCellRead(BaseModel):
    lesson_id: UUID
    lesson_title: str
    content_type: str
    is_completed: bool
    quiz_score: float | None
    effective_score: float | None
    manual_score: float | None
    teacher_comment: str | None
    completed_at: datetime | None
    progress_id: UUID | None


class GradebookAssignmentColumn(BaseModel):
    """One column in the assignment axis (live-read from AssignmentSubmission,
    independent of the per-lesson LessonProgress cells)."""

    assignment_id: UUID
    title: str
    lesson_id: UUID
    max_points: float


class GradebookAssignmentCell(BaseModel):
    assignment_id: UUID
    status: str | None  # submission status, or None if the student has none
    points_awarded: float | None
    score: float | None  # normalized 0..1
    submission_id: UUID | None


class GradebookStudentRow(BaseModel):
    student_id: UUID
    student_name: str
    student_email: str
    lessons: list[GradebookCellRead]
    assignments: list[GradebookAssignmentCell] = []


class GradebookRead(BaseModel):
    course_id: UUID
    course_title: str
    students: list[GradebookStudentRow]
    assignments: list[GradebookAssignmentColumn] = []


class ProgressUpdate(BaseModel):
    manual_score: float | None = Field(default=None, ge=0, le=100)
    teacher_comment: str | None = None


class StudentLessonProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    effective_score: float | None
    teacher_comment: str | None
    is_completed: bool


class StudentCourseDetailRead(CourseDetail):
    lesson_progress: dict[str, StudentLessonProgressRead] = {}
