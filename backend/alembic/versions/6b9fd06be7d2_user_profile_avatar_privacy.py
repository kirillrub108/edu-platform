"""user profile avatar privacy

Revision ID: 6b9fd06be7d2
Revises: d3c81a5f9b04
Create Date: 2026-08-29 14:28:20.512684

Adds the public-profile surface to `users`: a bio, the avatar pair
(uploaded path + provider URL, mirroring the course-cover pair), and the two
privacy knobs.

Autogenerate emitted `sa.Enum(...)` inline for `profile_visibility`, which
makes add_column try to CREATE TYPE implicitly; the type is created explicitly
here and the column then references it with `create_type=False`, the same shape
as f4e9b6f10146.

Defaults differ per role and a server_default cannot express that, so the
columns land with the student defaults and one UPDATE lifts teachers to the
open ones. New rows get their values from profile_service.
profile_defaults_for_role at registration, not from these defaults.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6b9fd06be7d2"
down_revision: Union[str, None] = "d3c81a5f9b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VISIBILITY = ("public", "authenticated", "private")


def upgrade() -> None:
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("avatar_image_path", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("avatar_external_url", sa.String(length=512), nullable=True))

    sa.Enum(*_VISIBILITY, name="profile_visibility").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column(
            "profile_visibility",
            postgresql.ENUM(*_VISIBILITY, name="profile_visibility", create_type=False),
            server_default="authenticated",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "show_profile_stats", sa.Boolean(), server_default="false", nullable=False
        ),
    )

    # Teachers are public-facing authors: their profile is the page a prospective
    # student lands on, so existing teacher rows get the open defaults.
    op.execute(
        "UPDATE users SET profile_visibility = 'public', show_profile_stats = true "
        "WHERE role = 'teacher'"
    )


def downgrade() -> None:
    op.drop_column("users", "show_profile_stats")
    op.drop_column("users", "profile_visibility")
    sa.Enum(name="profile_visibility").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "avatar_external_url")
    op.drop_column("users", "avatar_image_path")
    op.drop_column("users", "bio")
