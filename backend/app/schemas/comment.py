from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.constants import AVATAR_URL_TTL_SECONDS
from app.models.user import UserRole
from app.services.storage_service import storage_service


def _strip_before(v: object) -> object:
    """Pre-validator: strip incoming string so `min_length=1` rejects
    whitespace-only inputs with the standard built-in error (which is
    JSON-serializable, unlike user-raised ValueError that bundles a
    Python exception into `ctx.error`)."""
    return v.strip() if isinstance(v, str) else v


class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    _strip_content = field_validator("content", mode="before")(_strip_before)


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    _strip_content = field_validator("content", mode="before")(_strip_before)


class CommentAuthor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str | None
    role: UserRole
    # Source columns for avatar_url below; excluded from the response so the
    # client sees one field, matching every other place a person is rendered.
    avatar_image_path: str | None = Field(default=None, exclude=True)
    avatar_external_url: str | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        # Uploaded wins over the provider's, same rule as profile_service.
        # Signed under the author's own id - see profile_service.avatar_url on
        # why that is not an access check.
        if self.avatar_image_path:
            return storage_service.get_url(
                self.avatar_image_path, str(self.id), expires_in=AVATAR_URL_TTL_SECONDS
            )
        return self.avatar_external_url


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    content: str
    author: CommentAuthor
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_edited(self) -> bool:
        # Both timestamps come from the same `now()` in one transaction on
        # INSERT (Postgres `now()` is transaction-start time), so they are
        # exactly equal on creation. UPDATE runs in a separate transaction
        # and bumps `updated_at` to a strictly later value.
        return self.updated_at > self.created_at


class CommentListResponse(BaseModel):
    items: list[CommentRead]
    total: int
