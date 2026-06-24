from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.user import UserRole
from app.schemas.user import UserOut

# Shared password constraint — the single source of truth for "what counts as an
# acceptable password" across registration, reset, and change.
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]


class UserRegister(BaseModel):
    email: EmailStr
    password: PasswordStr
    full_name: str | None = None
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


__all__ = [
    "UserRegister",
    "UserLogin",
    "TokenResponse",
    "VerifyEmailRequest",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "ChangePasswordRequest",
    "UserOut",
]
