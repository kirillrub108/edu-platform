from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SlideTextOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slide_number: int
    image_url: str | None = None
    image_path: str | None = None
    generated_text: str
    edited_text: str | None
    is_edited: bool
    created_at: datetime
    updated_at: datetime


class SlideTextUpdate(BaseModel):
    edited_text: str


class SlideListResponse(BaseModel):
    lesson_id: UUID
    status: str
    total: int
    slides: list[SlideTextOut]


class AnalyzeStatusResponse(BaseModel):
    status: str
    step: str | None = None
    done: int | None = None
    total: int | None = None
    task_id: str | None = None
    error: str | None = None
