from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.lesson import ContentType, LessonStatus


class LessonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    module_id: UUID
    content_type: ContentType = ContentType.video
    order: int = 0


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    order: int | None = None
    content_type: ContentType | None = None
    video_url: str | None = None
    text_content: str | None = None
    script: str | None = None
    status: LessonStatus | None = None


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    module_id: UUID
    title: str
    order: int
    content_type: ContentType
    video_url: str | None
    text_content: str | None
    script: str | None
    status: LessonStatus
    created_at: datetime
    updated_at: datetime


class QuizQuestionCreate(BaseModel):
    question: str
    options: list[str]
    correct_index: int = Field(ge=0)
    order: int = 0


class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    options: list[str]
    correct_index: int
    order: int


class ScriptUpdateRequest(BaseModel):
    script: str


class VideoGenerateRequest(BaseModel):
    lesson_id: UUID
    pptx_path: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
