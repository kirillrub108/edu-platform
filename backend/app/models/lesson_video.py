import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class LessonVideo(Base):
    __tablename__ = "lesson_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    video_url = Column(String(512), nullable=False)
    voice = Column(String(64), nullable=False)
    creation_mode = Column(String(64), nullable=False)
    # SpeechKit-only hints (see VideoGenerateRequest); null when unset or when
    # the active TTS provider ignores them (silero/polza).
    speed = Column(Float, nullable=True)
    pitch = Column(Integer, nullable=True)
    is_published = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lesson = relationship("Lesson", back_populates="videos")
