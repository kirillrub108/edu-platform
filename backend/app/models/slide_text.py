import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class SlideText(Base):
    __tablename__ = "slide_texts"
    __table_args__ = (
        UniqueConstraint("lesson_id", "slide_number", name="uq_slide_lesson_number"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    slide_number = Column(Integer, nullable=False)
    generated_text = Column(Text, nullable=False, default="")
    edited_text = Column(Text, nullable=True)
    image_path = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lesson = relationship("Lesson", back_populates="slide_texts")
