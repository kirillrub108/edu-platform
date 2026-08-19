"""ai grading metering and paid attachment retention

Adds the two retention columns on assignment_submissions and the two new
credit_operation values the metering paths write (QUIZ_GRADE for AI-grading
overage, RETENTION_EXTEND for a paid retention extension). Alembic autogenerate
does not diff enum *values*, so the ALTER TYPEs below are hand-written.

Revision ID: a02faeb0b435
Revises: 3f6440d57557
Create Date: 2026-08-18 23:15:26.979584

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a02faeb0b435"
down_revision: Union[str, None] = "3f6440d57557"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_OPERATIONS = ("QUIZ_GRADE", "RETENTION_EXTEND")


def upgrade() -> None:
    op.add_column(
        "assignment_submissions",
        sa.Column("attachments_retain_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column("retention_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # IF NOT EXISTS keeps this idempotent if the enum was patched by hand.
    # PostgreSQL 12+ allows ADD VALUE inside a transaction as long as the new
    # label is not used in the same transaction — nothing here writes one.
    for value in _NEW_OPERATIONS:
        op.execute(f"ALTER TYPE credit_operation ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.drop_column("assignment_submissions", "retention_reminder_sent_at")
    op.drop_column("assignment_submissions", "attachments_retain_until")
    # PostgreSQL cannot DROP a single enum label; the type is rebuilt without
    # the two new values, which requires no row to still reference them.
    op.execute(
        "DELETE FROM credit_transactions WHERE operation::text IN "
        "('QUIZ_GRADE', 'RETENTION_EXTEND')"
    )
    op.execute("ALTER TYPE credit_operation RENAME TO credit_operation_old")
    op.execute(
        "CREATE TYPE credit_operation AS ENUM ("
        "'GRANT', 'LESSON_GENERATE', 'LESSON_REGEN', 'SLIDE_REGEN', 'VISION_ANALYZE', "
        "'QUIZ_GENERATE', 'AI_REVIEW', 'RESERVE', 'RELEASE', 'TOPUP', 'PURCHASE', 'EXPIRE')"
    )
    op.execute(
        "ALTER TABLE credit_transactions ALTER COLUMN operation TYPE credit_operation "
        "USING operation::text::credit_operation"
    )
    op.execute("DROP TYPE credit_operation_old")
