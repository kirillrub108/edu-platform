import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AccessMode(str, enum.Enum):
    link = "link"
    code = "code"
    invite = "invite"


class Course(Base):
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    cover_url = Column(String(512), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_mode = Column(
        SAEnum(AccessMode, name="access_mode"),
        default=AccessMode.link,
        nullable=False,
    )
    access_code = Column(String(20), nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User", back_populates="courses")
    modules = relationship(
        "Module",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Module.order",
    )
    enrollments = relationship(
        "Enrollment", back_populates="course", cascade="all, delete-orphan"
    )
