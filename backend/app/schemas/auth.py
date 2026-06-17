from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

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
