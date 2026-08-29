"""oauth accounts + nullable users.hashed_password

Revision ID: d3c81a5f9b04
Revises: f4e9b6f10146
Create Date: 2026-08-28

Social sign-in: one row per (provider, provider_user_id) linked to a local
user, and users.hashed_password becomes nullable so an account created purely
through a provider can exist without a local password.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3c81a5f9b04"
down_revision: Union[str, None] = "f4e9b6f10146"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_identity"),
    )
    op.create_index(
        op.f("ix_oauth_accounts_user_id"), "oauth_accounts", ["user_id"], unique=False
    )
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Password-less (social-only) accounts cannot survive the NOT NULL. They
    # only exist because of this feature, so dropping them is the honest
    # inverse — anything else would leave the column unrestorable.
    op.execute(
        "DELETE FROM users WHERE id IN (SELECT user_id FROM oauth_accounts) "
        "AND hashed_password IS NULL"
    )
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=False)
    op.drop_index(op.f("ix_oauth_accounts_user_id"), table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
