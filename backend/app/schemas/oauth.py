"""DTOs for social sign-in. Three of them are wire schemas (start request /
response, complete request); the other three are the typed shapes of what the
service parks in Redis, so nothing round-trips through a bare dict."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.user import UserRole

OAuthProviderName = Literal["google", "yandex"]


class OAuthStartRequest(BaseModel):
    remember_me: bool = True
    # Post-login SPA destination. Path-only: a single leading "/" never followed
    # by "/" or "\", so the value can't become a protocol-relative off-site URL.
    # (No look-ahead — pydantic-core's regex engine doesn't support it.)
    next: str | None = Field(default=None, max_length=512, pattern=r"^/($|[^/\\].*)$")


class OAuthStartResponse(BaseModel):
    authorize_url: str


class OAuthCompleteRequest(BaseModel):
    ticket: str = Field(min_length=1, max_length=512)
    role: UserRole
    pdn_consent: bool = False
    offer_consent: bool = False
    marketing_consent: bool = False

    @model_validator(mode="after")
    def _require_mandatory_consents(self) -> "OAuthCompleteRequest":
        missing = [
            name
            for name, accepted in (
                ("pdn_consent", self.pdn_consent),
                ("offer_consent", self.offer_consent),
            )
            if not accepted
        ]
        if missing:
            raise ValueError(f"Required consents not accepted: {', '.join(missing)}")
        return self


class StartedFlow(BaseModel):
    """Redis value at oauth:state:{state}."""

    provider: OAuthProviderName
    code_verifier: str
    remember_me: bool
    next: str | None
    created_at: datetime


class OAuthProfile(BaseModel):
    """Normalized provider profile. ``email`` is already lower-cased."""

    provider: OAuthProviderName
    provider_user_id: str
    email: str
    full_name: str | None


class PendingTicket(BaseModel):
    """Redis value at oauth:pending:{ticket} - branch C, no user row yet."""

    provider: OAuthProviderName
    provider_user_id: str
    email: str
    full_name: str | None
    created_at: datetime


__all__ = [
    "OAuthProviderName",
    "OAuthStartRequest",
    "OAuthStartResponse",
    "OAuthCompleteRequest",
    "StartedFlow",
    "OAuthProfile",
    "PendingTicket",
]
