import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CreditPlan(str, enum.Enum):
    # Values match PLAN_CONFIGS keys in app.constants.
    free = "free"
    starter = "starter"
    pro = "pro"
    school = "school"


class CreditOperation(str, enum.Enum):
    # name == value (uppercase) so sync Celery wrappers can resolve the enum
    # from the plain string they receive via CreditOperation(operation_str).
    GRANT = "GRANT"
    LESSON_GENERATE = "LESSON_GENERATE"
    LESSON_REGEN = "LESSON_REGEN"
    SLIDE_REGEN = "SLIDE_REGEN"
    VISION_ANALYZE = "VISION_ANALYZE"
    QUIZ_GENERATE = "QUIZ_GENERATE"
    AI_REVIEW = "AI_REVIEW"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    TOPUP = "TOPUP"
    PURCHASE = "PURCHASE"
    EXPIRE = "EXPIRE"


class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    # See User.__mapper_args__ for rationale (onupdate=func.now() needs this).
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    plan = Column(
        SAEnum(CreditPlan, name="credit_plan"),
        default=CreditPlan.free,
        nullable=False,
    )
    balance = Column(Integer, default=0, nullable=False)
    reserved = Column(Integer, default=0, nullable=False)
    monthly_allowance = Column(Integer, default=0, nullable=False)
    allowance_resets_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    transactions = relationship(
        "CreditTransaction",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="CreditTransaction.created_at.desc()",
    )


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("credit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Per-operation credit movement (positive = credited, negative = debited).
    # RESERVE/RELEASE move the reserved hold; GRANT/TOPUP/EXPIRE and the
    # LESSON_*/SLIDE_*/VISION_* operations move the balance. Because both the
    # hold and the balance are logged, summing all deltas does NOT reconstruct
    # the balance — filter by operation if you need that.
    delta = Column(Integer, nullable=False)
    operation = Column(
        SAEnum(CreditOperation, name="credit_operation"),
        nullable=False,
    )
    ref_id = Column(String(64), nullable=True)  # lesson_id / task_id / slide_id for audit
    description = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    account = relationship("CreditAccount", back_populates="transactions")
