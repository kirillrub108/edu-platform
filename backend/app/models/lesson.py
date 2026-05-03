import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ContentType(str, enum.Enum):
    video = "video"
    text = "text"
    quiz = "quiz"


class LessonStatus(str, enum.Enum):
    draft = "draft"
    processing = "processing"
    published = "published"
    error = "error"


class Module(Base):
    __tablename__ = "modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    course = relationship("Course", back_populates="modules")
    lessons = relationship(
        "Lesson",
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="Lesson.order",
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id = Column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0, nullable=False)
    content_type = Column(
        SAEnum(ContentType, name="content_type"),
        default=ContentType.video,
        nullable=False,
    )
    pptx_path = Column(String(512), nullable=True)
    video_url = Column(String(512), nullable=True)
    text_content = Column(Text, nullable=True)
    script = Column(Text, nullable=True)
    status = Column(
        SAEnum(LessonStatus, name="lesson_status"),
        default=LessonStatus.draft,
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    module = relationship("Module", back_populates="lessons")
    quiz_questions = relationship(
        "QuizQuestion",
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.order",
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    question = Column(Text, nullable=False)
    options = Column(JSONB, nullable=False)
    correct_index = Column(Integer, nullable=False)
    order = Column(Integer, default=0, nullable=False)

    lesson = relationship("Lesson", back_populates="quiz_questions")
