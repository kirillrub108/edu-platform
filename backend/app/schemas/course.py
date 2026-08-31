from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.constants import SOFT_DELETE_PURGE_DAYS
from app.models.course import AccessMode
from app.schemas.user import UserOut


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    cover_url: str | None = None


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    cover_url: str | None = None
    access_mode: AccessMode | None = None
    access_code: str | None = None
    is_published: bool | None = None


class CoursePartialUpdate(BaseModel):
    """Inline-edit: only title and description; title must be non-empty if provided."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ModuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    order: int = 0


class ModuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)


class LessonShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    order: int
    content_type: str
    status: str
    is_published: bool


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    order: int
    is_published: bool
    lessons: list[LessonShort] = []


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    cover_url: str | None
    cover_image_url: str | None = None
    access_mode: AccessMode
    access_code: str | None
    is_published: bool
    # Optional because the global soft-delete filter hides a deleted teacher, so
    # Course.owner loads as None while their courses live on — during the
    # restore window, and permanently once purge anonymizes the row instead of
    # deleting it (DECISIONS §59). The UI renders "Удалённый пользователь".
    owner: UserOut | None = None
    created_at: datetime
    updated_at: datetime
    lessons_count: int = 0
    enrollment_count: int = 0
    # Source column for the computed fields below; not serialized itself.
    deleted_at: datetime | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_archived(self) -> bool:
        return self.deleted_at is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def access_restricted(self) -> bool:
        """`invite` is the restricted mode — see services/course_access_service."""
        return self.access_mode == AccessMode.invite

    @computed_field  # type: ignore[prop-decorator]
    @property
    def days_until_purge(self) -> int | None:
        """Whole days left before purge, clamped at 0.

        None when the course is not archived — and also when anybody is enrolled:
        purge retains an archived course with at least one enrollment forever
        (app/tasks/purge_pipeline.py), so there is no countdown to show. Callers
        that surface this MUST populate `enrollment_count`, or the UI promises a
        deletion that will never happen.
        """
        if self.deleted_at is None or self.enrollment_count > 0:
            return None
        deleted = self.deleted_at
        if deleted.tzinfo is None:
            deleted = deleted.replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - deleted).days
        return max(0, SOFT_DELETE_PURGE_DAYS - days_since)


class StudentCourseOut(CourseOut):
    completed_lessons: int = 0


class CourseDetail(CourseOut):
    modules: list[ModuleOut] = []


class PreviewLessonRead(LessonShort):
    visible_to_student: bool = False


class PreviewModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    order: int
    is_published: bool
    visible_to_student: bool = False
    lessons: list[PreviewLessonRead] = []


class CoursePreviewTreeRead(BaseModel):
    """Owner-only 'view as student' tree: the FULL module/lesson list where
    every node carries its effective student visibility."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    is_published: bool
    modules: list[PreviewModuleRead] = []


class CoursePreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    access_mode: AccessMode
    is_published: bool


class CourseGroupedResponse(BaseModel):
    published: list[CourseOut] = []
    drafts: list[CourseOut] = []
    archived: list[CourseOut] = []


class CourseAccessModeUpdate(BaseModel):
    mode: Literal["open", "restricted"]


class CourseAccessGrantCreate(BaseModel):
    student_id: UUID


class CourseAccessGrantRead(BaseModel):
    """One entry of a restricted course's student list."""

    model_config = ConfigDict(from_attributes=True)

    student_id: UUID
    email: str
    full_name: str | None = None
    created_at: datetime


class AccessGrantCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None
