from datetime import datetime, timezone
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
    owner: UserOut
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
    def days_until_purge(self) -> int | None:
        """Whole days left before purge; None if not archived, clamped at 0."""
        if self.deleted_at is None:
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
