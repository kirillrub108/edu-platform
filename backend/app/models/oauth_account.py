import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class OAuthAccount(Base):
    """A social identity (Google / Yandex) linked to a local user.

    One row per (provider, provider_user_id). The provider's subject id — not
    the email — is the identity key, so a user renaming their mailbox at the
    provider keeps the same local account.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_oauth_identity"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String(32), nullable=False)
    provider_user_id = Column(String(255), nullable=False)
    # Email as the provider reported it at link time — audit trail only; the
    # authoritative address stays users.email.
    email = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
