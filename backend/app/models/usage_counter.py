import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class UsageResource(str, enum.Enum):
    # Metered AI operations. Values double as TIER_QUOTAS monthly-key suffixes
    # via _RESOURCE_QUOTA_KEY in services/quota_service.py.
    video = "video"
    vision = "vision"


class UsageCounter(Base):
    """Per-user monthly usage tally for one metered resource.

    Source of truth for tier monthly quotas (Postgres, not Redis). One row per
    (user, period_key, resource); `period_key` is "YYYY-MM" so a new month is a
    new row and old months expire naturally. Reservation is an atomic UPSERT
    guarded by the tier limit — see services/quota_service.py.
    """

    __tablename__ = "usage_counters"
    # See User.__mapper_args__ for rationale (onupdate=func.now() needs this to
    # avoid MissingGreenlet when the row is serialized right after UPDATE).
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_key = Column(String(7), nullable=False)  # "YYYY-MM"
    resource = Column(SAEnum(UsageResource, name="usage_resource"), nullable=False)
    count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_key", "resource", name="uq_usage_counter_user_period_resource"
        ),
    )
