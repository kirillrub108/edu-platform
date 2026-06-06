from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class ModuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    order: int = 0


class LessonShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    order: int
    content_type: str
    status: str


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    order: int
    lessons: list[LessonShort] = []


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    cover_url: str | None
    access_mode: AccessMode
    access_code: str | None
    is_published: bool
    owner: UserOut
    created_at: datetime
    updated_at: datetime
    lessons_count: int = 0


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
