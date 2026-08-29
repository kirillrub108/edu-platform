from typing import Annotated

from disposable_email_domains import blocklist
from pydantic import AfterValidator, BaseModel, EmailStr, Field, model_validator

from app.models.user import UserRole
from app.schemas.user import UserOut


def _reject_blank_password(value: str) -> str:
    """A password made entirely of whitespace is not a password. Checked after
    the length constraint below, so it catches e.g. 8 spaces too — raw length
    alone would let it through."""
    if not value.strip():
        raise ValueError("password_blank")
    return value


# Shared password constraint — the single source of truth for "what counts as an
# acceptable password" across registration, reset, and change.
PasswordStr = Annotated[
    str, Field(min_length=8, max_length=128), AfterValidator(_reject_blank_password)
]


def is_disposable_domain(domain: str) -> bool:
    """True if `domain` or any of its parent domains is a known disposable provider."""
    labels = domain.lower().split(".")
    return any(".".join(labels[i:]) in blocklist for i in range(len(labels) - 1))


class UserRegister(BaseModel):
    email: EmailStr
    password: PasswordStr
    # Mirrors the User.full_name column (String(255)) — a longer value must be a
    # 422, not a 500 from a truncated INSERT.
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.teacher
    # Consents. The two required ones must be explicitly true — the server never
    # trusts the client alone, so missing/false here is a 422 and no user is
    # created. Marketing is optional and defaults to off.
    accepted_privacy: bool = False
    accepted_terms: bool = False
    accepted_marketing: bool = False

    @model_validator(mode="after")
    def _require_mandatory_consents(self) -> "UserRegister":
        missing = [
            name
            for name, accepted in (
                ("accepted_privacy", self.accepted_privacy),
                ("accepted_terms", self.accepted_terms),
            )
            if not accepted
        ]
        if missing:
            raise ValueError(f"Required consents not accepted: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _reject_disposable_email(self) -> "UserRegister":
        if is_disposable_domain(self.email.split("@")[-1]):
            raise ValueError("disposable_email_not_allowed")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = True


class TokenResponse(BaseModel):
    """Internal DTO returned by AuthService. Not exposed in API responses."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: PasswordStr


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: PasswordStr


class DeleteAccountRequest(BaseModel):
    """Re-authentication for self-deletion. The session cookie alone is not
    enough for an action this destructive."""

    password: str


class RestoreAccountRequest(BaseModel):
    """Either the signed token from the deletion email, or the original
    credentials. Both routes end in the same restore."""

    token: str | None = None
    email: EmailStr | None = None
    password: str | None = None


class ReleaseEmailRequest(BaseModel):
    email: EmailStr


class ConfirmReleaseRequest(BaseModel):
    token: str


__all__ = [
    "UserRegister",
    "UserLogin",
    "TokenResponse",
    "VerifyEmailRequest",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "ChangePasswordRequest",
    "DeleteAccountRequest",
    "RestoreAccountRequest",
    "ReleaseEmailRequest",
    "ConfirmReleaseRequest",
    "UserOut",
    "is_disposable_domain",
]
