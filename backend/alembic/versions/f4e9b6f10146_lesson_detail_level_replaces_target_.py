"""lesson detail level replaces target duration

Revision ID: f4e9b6f10146
Revises: 7b72507955ba
Create Date: 2026-08-27 07:21:33.488752

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f4e9b6f10146'
down_revision: Union[str, None] = '7b72507955ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The type is created explicitly, so the column must NOT try to create it
    # again (create_type=False) — otherwise add_column raises DuplicateObject.
    sa.Enum("brief", "auto", "high", name="detail_level").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "lessons",
        sa.Column(
            "detail_level",
            postgresql.ENUM("brief", "auto", "high", name="detail_level", create_type=False),
            nullable=False,
            server_default="auto",
        ),
    )
    # target_duration_min is deliberately NOT dropped here: expand/contract
    # (docs/DECISIONS.md §53) — the previous release still writes it while both
    # run side by side. The contract step is tracked in docs/KNOWN_PROBLEMS.md.


def downgrade() -> None:
    op.drop_column("lessons", "detail_level")
    sa.Enum(name="detail_level").drop(op.get_bind(), checkfirst=True)
