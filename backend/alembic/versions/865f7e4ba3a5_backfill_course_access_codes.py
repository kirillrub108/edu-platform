"""backfill course access codes

Revision ID: 865f7e4ba3a5
Revises: c2f900c2bf7a
Create Date: 2026-08-15 22:06:59.772472

Data migration only: the courses.access_code column is already UNIQUE (see
c2f900c2bf7a) and stays NULLable on purpose — deleting a course's access
code (routers/courses.py:delete_access_code) sets it back to NULL as a
deliberate "link-only" state, so a NOT NULL constraint would fight that
existing, tested behavior. This just assigns a code to rows that never got
one (autogenerate found no schema drift to apply).
"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import IntegrityError

from app.constants import ACCESS_CODE_ALPHABET, ACCESS_CODE_LENGTH, ACCESS_CODE_MAX_RETRIES

revision: str = '865f7e4ba3a5'
down_revision: Union[str, None] = 'c2f900c2bf7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _random_code() -> str:
    return "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(ACCESS_CODE_LENGTH))


def upgrade() -> None:
    bind = op.get_bind()
    course_ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM courses WHERE access_code IS NULL OR access_code = ''")
        )
    ]
    for course_id in course_ids:
        # One savepoint per row so a UNIQUE collision (astronomically unlikely
        # at ACCESS_CODE_LENGTH=6 over a 33-char alphabet) only re-rolls that
        # row instead of aborting the whole backfill.
        for _ in range(ACCESS_CODE_MAX_RETRIES):
            nested = bind.begin_nested()
            try:
                bind.execute(
                    sa.text("UPDATE courses SET access_code = :code WHERE id = :id"),
                    {"code": _random_code(), "id": course_id},
                )
                nested.commit()
                break
            except IntegrityError:
                nested.rollback()
        else:
            raise RuntimeError(f"Could not generate a unique access_code for course {course_id}")


def downgrade() -> None:
    # Not reversible: codes we generated here can't be distinguished from
    # ones that already existed, so there's nothing safe to undo.
    pass
