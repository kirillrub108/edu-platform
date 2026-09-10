"""Addresses we must stop mailing.

Written from the Resend delivery webhook (see tasks/email_pipeline.
handle_email_delivery_event) and read before every send. A row here is a
*permanent* verdict about the address, not about one message: a hard bounce
means the mailbox does not exist, a complaint means the owner pressed "spam".
Both make further sending harmful — to the address owner and to our sending
reputation — so send_email drops such mail instead of retrying it.

Soft bounces (full mailbox, greylisting) deliberately never land here; they are
transient and only get logged.
"""

import enum
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class SuppressionReason(str, enum.Enum):
    hard_bounce = "hard_bounce"
    complaint = "complaint"
    # Reserved for an operator adding an address by hand (grant_credits-style
    # CLI or a DB fix). No code path writes it today.
    manual = "manual"


class EmailSuppression(Base):
    __tablename__ = "email_suppressions"
    # `updated_at` carries onupdate=func.now(); without eager_defaults the value
    # is left expired after UPDATE and a later attribute read raises
    # MissingGreenlet on the async session. Same rule as User.
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stored lowercase (the service normalizes) so the unique index doubles as
    # the case-insensitive lookup key — no func.lower() index needed.
    email = Column(String(255), unique=True, index=True, nullable=False)
    reason = Column(SAEnum(SuppressionReason, name="suppression_reason"), nullable=False)
    detail = Column(Text, nullable=True)
    # Provider's id for the message that triggered the LATEST event. Kept for
    # support ("which message bounced?"); event-level idempotency is Redis-based
    # on svix-id, not this column.
    provider_message_id = Column(String(255), nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Independent later events for the same address. A redelivery of the SAME
    # event never increments this — see email_suppression_service.record_event.
    hits = Column(Integer, server_default="1", nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
