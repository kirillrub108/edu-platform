import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Comment(Base):
    __tablename__ = "comments"
    # See User.__mapper_args__ for rationale: needed for any model with
    # onupdate=func.now() to avoid MissingGreenlet on async commit→serialize.
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_comments_lesson_created", "lesson_id", "created_at"),
        Index("ix_comments_author_id", "author_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # `clock_timestamp()` (not `now()`) for onupdate so `is_edited =
    # updated_at > created_at` is reliable: `now()` is transaction-start time
    # and stays frozen across statements in the same transaction (which would
    # make an edit-in-same-tx look unedited).
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        nullable=False,
    )

    author = relationship("User", lazy="joined")
    lesson = relationship("Lesson")
