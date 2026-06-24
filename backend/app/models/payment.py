import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    canceled = "canceled"


class Payment(Base):
    """One YooKassa payment attempt for a credit package.

    Credits are granted exactly once: apply_purchase locks this row, flips
    status pending → succeeded and writes the PURCHASE ledger transaction in
    the same DB transaction, so webhook redelivery and status polling can
    both call it safely.
    """

    __tablename__ = "payments"
    # See User.__mapper_args__ for rationale (onupdate=func.now() needs this).
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    package_key = Column(String(32), nullable=False)
    amount_rub = Column(Numeric(10, 2), nullable=False)
    credits = Column(Integer, nullable=False)
    status = Column(
        SAEnum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.pending,
        nullable=False,
    )
    yookassa_payment_id = Column(String(64), nullable=True, unique=True)
    # Our Idempotence-Key sent to YooKassa on create — retrying the create call
    # with the same key can never produce a second charge.
    idempotence_key = Column(String(64), nullable=False)
    # Audit timestamps set during settlement (apply_purchase / the webhook task).
    # refunded_at records a refund.succeeded event; spent credits are NOT clawed
    # back automatically (see docs/DECISIONS.md).
    paid_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    # Set by the reconcile sweep when a payment is flagged as stuck-in-pending,
    # so the alert fires exactly once per payment (no spam across sweeps).
    alerted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
