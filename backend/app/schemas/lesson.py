from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.lesson import ContentType, CreationMode, LessonStatus


class LessonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    module_id: UUID
    content_type: ContentType = ContentType.video
    order: int = 0
    creation_mode: CreationMode = CreationMode.presentation_and_text


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    order: int | None = None
    content_type: ContentType | None = None
    video_url: str | None = None
    text_content: str | None = None
    script: str | None = None
    status: LessonStatus | None = None
    creation_mode: CreationMode | None = None


class LessonVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    video_url: str
    voice: str
    creation_mode: str
    is_published: bool
    created_at: datetime


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    module_id: UUID
    title: str
    order: int
    content_type: ContentType
    pptx_path: str | None
    video_url: str | None
    text_content: str | None
    script: str | None
    status: LessonStatus
    creation_mode: CreationMode
    analyze_task_id: str | None = None
    video_task_id: str | None = None
    last_warning: str | None = None
    published_video: LessonVideoOut | None = None
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


SILERO_VOICES = ["aidar", "baya", "kseniya", "xenia", "eugene"]


class VideoGenerateRequest(BaseModel):
    pptx_path: str | None = None
    voice: str = Field(default="xenia", pattern="^(aidar|baya|kseniya|xenia|eugene)$")


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    meta: dict | None = None
    progress_pct: int | None = None
    error: str | None = None
    traceback: str | None = None
