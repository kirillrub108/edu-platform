import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ACCESS_CODE_ALPHABET, ACCESS_CODE_LENGTH, ACCESS_CODE_MAX_RETRIES
from app.models.course import AccessMode, Course


async def generate_unique_access_code(db: AsyncSession) -> str:
    for _ in range(ACCESS_CODE_MAX_RETRIES):
        code = "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(ACCESS_CODE_LENGTH))
        taken = await db.scalar(select(Course.id).where(Course.access_code == code).limit(1))
        if not taken:
            return code
    raise HTTPException(status_code=500, detail="Failed to generate unique access code")


async def assign_unique_access_code(
    db: AsyncSession, course: Course, access_mode: AccessMode | None = None
) -> None:
    """Generate and persist a fresh access_code on `course`, retrying the whole
    generate+commit cycle on a UNIQUE-index race: `generate_unique_access_code`
    only pre-checks via SELECT, which isn't atomic with the write, so a
    concurrent request can still grab the same code before we commit. Rolling
    back re-sets `access_mode` too since a failed commit expires the pending
    in-memory change along with `access_code`.
    """
    for _ in range(ACCESS_CODE_MAX_RETRIES):
        course.access_code = await generate_unique_access_code(db)
        if access_mode is not None:
            course.access_mode = access_mode
        try:
            await db.commit()
            return
        except IntegrityError:
            await db.rollback()
    raise HTTPException(status_code=500, detail="Failed to generate unique access code")
