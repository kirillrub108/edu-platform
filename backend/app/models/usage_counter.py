import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class UsageCounter(Base):
    """Durable per-user usage counter (quota_service).

    Keyed by (user_id, period_key, resource); incremented with an atomic
    INSERT ... ON CONFLICT DO UPDATE ... WHERE count < :limit RETURNING. The
    lifetime trial uses period_key='lifetime' with resources 'trial_lecture'
    and 'trial_quiz'.
    """

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_key", "resource", name="uq_usage_counters_user_period_resource"
        ),
    )
    # See User.__mapper_args__ for rationale (onupdate=func.now() needs this).
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_key = Column(String(32), nullable=False)
    # 64, not 32: the daily grading cap stores 'grading_attempt:{quiz_uuid}' (52).
    resource = Column(String(64), nullable=False)
    count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
