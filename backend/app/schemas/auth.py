from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole
from app.schemas.user import UserOut


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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


__all__ = [
    "UserRegister",
    "UserLogin",
    "TokenResponse",
    "VerifyEmailRequest",
    "UserOut",
]
