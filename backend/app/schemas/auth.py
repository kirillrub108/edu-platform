from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserOut


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


__all__ = ["UserRegister", "UserLogin", "TokenResponse", "RefreshRequest", "UserOut"]
