import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
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
    CourseGroupedResponse,
    CourseOut,
    CoursePartialUpdate,
    CourseUpdate,
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
)
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


_COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_COVER_BYTES = 5 * 1024 * 1024


def _course_out(course: Course, user_id: str) -> CourseOut:
    out = CourseOut.model_validate(course)
    out.cover_url = storage_service.resign_url(out.cover_url, user_id)
    if course.cover_image_path:
        out.cover_image_url = storage_service.get_url(course.cover_image_path, user_id)
    elif out.cover_url:
        out.cover_image_url = out.cover_url  # already re-signed above
    return out


def _course_detail_out(course: Course, user_id: str) -> CourseDetail:
    out = CourseDetail.model_validate(course)
    out.cover_url = storage_service.resign_url(out.cover_url, user_id)
    if course.cover_image_path:
        out.cover_image_url = storage_service.get_url(course.cover_image_path, user_id)
    elif out.cover_url:
        out.cover_image_url = out.cover_url  # already re-signed above
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


async def _get_owned_module(
    course_id: UUID, module_id: UUID, owner: User, db: AsyncSession
) -> Module:
    await _get_owned_course(course_id, owner, db)
    module = await db.get(Module, module_id)
    if not module or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Module not found")
    return module


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


# NOTE: must be declared before GET "/{course_id}" so "grouped" isn't parsed
# as a course_id UUID.
@router.get("/grouped", response_model=CourseGroupedResponse)
async def list_courses_grouped(
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Teacher dashboard view: all owned courses partitioned into
    published / drafts / archived (Course is not globally filtered, so archived
    rows are returned here). published & drafts sort by created_at desc,
    archived by deleted_at desc."""
    result = await db.scalars(
        select(Course)
        .where(Course.owner_id == user.id)
        .options(
            selectinload(Course.owner),
            selectinload(Course.modules).selectinload(Module.lessons),
        )
    )
    published: list[tuple[datetime, CourseOut]] = []
    drafts: list[tuple[datetime, CourseOut]] = []
    archived: list[tuple[datetime, CourseOut]] = []
    for course in result.all():
        course.lessons_count = sum(len(m.lessons) for m in course.modules)
        out = _course_out(course, str(user.id))
        if course.deleted_at is not None:
            archived.append((course.deleted_at, out))
        elif course.is_published:
            published.append((course.created_at, out))
        else:
            drafts.append((course.created_at, out))
    for bucket in (published, drafts, archived):
        bucket.sort(key=lambda pair: pair[0], reverse=True)
    return CourseGroupedResponse(
        published=[o for _, o in published],
        drafts=[o for _, o in drafts],
        archived=[o for _, o in archived],
    )


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


@router.patch("/{course_id}", response_model=CourseOut)
async def patch_course(
    course_id: UUID,
    data: CoursePartialUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(course, key, value)
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete (archive): the course is hidden from students and physically
    removed by the purge task after SOFT_DELETE_PURGE_DAYS. Idempotency guard:
    409 if already archived."""
    course = await _get_owned_course(course_id, user, db)
    if course.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Course already archived")
    course.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.patch("/{course_id}/restore", response_model=CourseOut)
async def restore_course(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_owned_course(course_id, user, db)
    if course.deleted_at is None:
        raise HTTPException(status_code=400, detail="Course is not archived")
    course.deleted_at = None
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))


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


@router.delete("/{course_id}/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(
    course_id: UUID,
    module_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_course(course_id, user, db)
    module = await db.get(Module, module_id)
    if not module or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Module not found")
    await db.delete(module)
    await db.commit()


@router.patch("/{course_id}/modules/{module_id}", response_model=ModuleOut)
async def patch_module(
    course_id: UUID,
    module_id: UUID,
    data: ModuleUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    module = await _get_owned_module(course_id, module_id, user, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(module, key, value)
    await db.commit()
    await db.refresh(module, attribute_names=["lessons"])
    return module


@router.post("/{course_id}/modules/{module_id}/publish", response_model=ModuleOut)
async def publish_module(
    course_id: UUID,
    module_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Publish a module. Independent of course/lesson flags; idempotent."""
    module = await _get_owned_module(course_id, module_id, user, db)
    module.is_published = True
    await db.commit()
    await db.refresh(module, attribute_names=["lessons"])
    return module


@router.post("/{course_id}/modules/{module_id}/unpublish", response_model=ModuleOut)
async def unpublish_module(
    course_id: UUID,
    module_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Unpublish a module. Lesson flags are left untouched — hiding is the
    read-time AND in visibility_service. Idempotent."""
    module = await _get_owned_module(course_id, module_id, user, db)
    module.is_published = False
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


@router.post("/{course_id}/cover", response_model=CourseOut)
async def upload_course_cover(
    course_id: UUID,
    file: UploadFile,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _COVER_EXTS:
        raise HTTPException(status_code=400, detail="Допустимые форматы: .jpg .jpeg .png .webp .gif")  # noqa: E501
    content = await file.read()
    if len(content) > _MAX_COVER_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 5 МБ)")
    await file.seek(0)

    course = await _get_owned_course(course_id, user, db)
    course.cover_image_path = await storage_service.save_upload(file, "covers")
    await db.commit()
    await db.refresh(course, attribute_names=["owner"])
    return _course_out(course, str(user.id))
