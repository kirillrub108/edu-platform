import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import ACCESS_CODE_ALPHABET, ACCESS_CODE_LENGTH, ACCESS_CODE_MAX_RETRIES
from app.database import get_db
from app.dependencies import require_teacher
from app.models.course import AccessMode, Course
from app.models.lesson import Module
from app.models.user import User
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseOut,
    CourseUpdate,
    ModuleCreate,
    ModuleOut,
)
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


def _course_out(course: Course, user_id: str) -> CourseOut:
    out = CourseOut.model_validate(course)
    out.cover_url = storage_service.resign_url(out.cover_url, user_id)
    return out


def _course_detail_out(course: Course, user_id: str) -> CourseDetail:
    out = CourseDetail.model_validate(course)
    out.cover_url = storage_service.resign_url(out.cover_url, user_id)
    return out


async def generate_unique_access_code(db: AsyncSession) -> str:
    for _ in range(ACCESS_CODE_MAX_RETRIES):
        code = "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(ACCESS_CODE_LENGTH))
        taken = await db.scalar(select(Course.id).where(Course.access_code == code).limit(1))
        if not taken:
            return code
    raise HTTPException(status_code=500, detail="Failed to generate unique access code")


async def _get_owned_course(course_id: UUID, owner: User, db: AsyncSession) -> Course:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != owner.id:
        raise HTTPException(status_code=403, detail="Not your course")
    return course


@router.get("/", response_model=list[CourseOut])
async def list_courses(
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Course)
        .where(Course.owner_id == user.id)
        .options(
            selectinload(Course.owner),
            selectinload(Course.modules).selectinload(Module.lessons),
        )
        .order_by(Course.created_at.desc())
    )
    courses = list(result.all())
    for course in courses:
        course.lessons_count = sum(len(m.lessons) for m in course.modules)
    return [_course_out(c, str(user.id)) for c in courses]


@router.post("/", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(
    data: CourseCreate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = Course(title=data.title, description=data.description, cover_url=data.cover_url, owner_id=user.id)
    db.add(course)
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


@router.get("/{course_id}", response_model=CourseDetail)
async def get_course(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.owner),
            selectinload(Course.modules).selectinload(Module.lessons),
        )
    )
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    return _course_detail_out(course, str(user.id))


@router.put("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: UUID,
    data: CourseUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(course, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="access_code already in use")
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    await db.delete(course)
    await db.commit()


@router.post(
    "/{course_id}/modules",
    response_model=ModuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_module(
    course_id: UUID,
    data: ModuleCreate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_course(course_id, user, db)
    module = Module(course_id=course_id, title=data.title, order=data.order)
    db.add(module)
    await db.commit()
    await db.refresh(module, attribute_names=["lessons"])
    return module


@router.put("/{course_id}/publish", response_model=CourseOut)
async def toggle_publish(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    course.is_published = not course.is_published
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


@router.post("/{course_id}/access-code/generate", response_model=CourseOut)
async def generate_access_code(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    course.access_code = await generate_unique_access_code(db)
    course.access_mode = AccessMode.code
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to generate unique access code")
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


@router.delete("/{course_id}/access-code", response_model=CourseOut)
async def delete_access_code(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    course.access_code = None
    course.access_mode = AccessMode.link
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))
