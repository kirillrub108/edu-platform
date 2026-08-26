"""notification preferences on users

Three boolean opt-out flags backing NotificationCategory (see
services/notification_service.py). server_default 'true' so existing rows are
backfilled opted-in — the flags only ever suppress product email, never auth
mail, so defaulting them on cannot silence a transactional message.

Revision ID: b41c9e7a52d0
Revises: 71a756b0c361
Create Date: 2026-08-26 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b41c9e7a52d0"
down_revision: Union[str, None] = "71a756b0c361"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("notify_content", "notify_feedback", "notify_submissions")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "users",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("users", name)
