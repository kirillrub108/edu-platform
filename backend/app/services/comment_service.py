from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.comment import Comment
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.lesson import Lesson, Module
from app.models.user import User, UserRole
from app.services import course_access_service
from app.services.notification_service import NotificationEvent, notify
from app.services.visibility_service import lesson_visible_to_student

logger = structlog.get_logger()


async def list_comments(
    db: AsyncSession,
    lesson_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Comment], int]:
    total = await db.scalar(
        select(func.count()).select_from(Comment).where(Comment.lesson_id == lesson_id)
    )

    result = await db.execute(
        select(Comment)
        .where(Comment.lesson_id == lesson_id)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), int(total or 0)


async def create_comment(
    db: AsyncSession,
    *,
    lesson_id: UUID,
    author_id: UUID,
    content: str,
) -> Comment:
    comment = Comment(lesson_id=lesson_id, author_id=author_id, content=content)
    db.add(comment)
    await db.commit()
    await db.refresh(comment, attribute_names=["author"])
    return comment


async def notify_students_of_comment(db: AsyncSession, lesson_id: UUID, author: User) -> None:
    """Fan a teacher's comment out to the students enrolled in the course.

    Gated on `lesson_visible_to_student` so a comment on an unpublished lesson
    (or under an unpublished module) never tells a student that lesson exists.
    Best-effort throughout: posting a comment must not fail because notification
    bookkeeping did.
    """
    if author.role is not UserRole.teacher:
        return
    try:
        lesson = await db.scalar(
            select(Lesson).where(Lesson.id == lesson_id).options(selectinload(Lesson.module))
        )
        if lesson is None or lesson.module is None:
            return
        if not lesson_visible_to_student(lesson.module, lesson):
            return
        student_ids = (
            (
                await db.execute(
                    select(Enrollment.student_id)
                    .join(Course, Enrollment.course_id == Course.id)
                    .where(
                        Enrollment.course_id == lesson.module.course_id,
                        course_access_service.access_clause(Enrollment.student_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        payload = {
            # Dedup scope is the lesson thread: five comments in a row collapse
            # to one mail per dedup window.
            "entity_id": str(lesson_id),
            "lesson_id": str(lesson_id),
            "lesson_title": lesson.title or "",
            "url": f"{settings.FRONTEND_URL}/student/lessons/{lesson_id}",
        }
        for student_id in student_ids:
            notify(student_id, NotificationEvent.comment_posted, payload)
    except Exception:
        logger.warning("comment_notify_failed", lesson_id=str(lesson_id), exc_info=True)


async def update_comment(
    db: AsyncSession,
    *,
    comment_id: UUID,
    user_id: UUID,
    content: str,
) -> Comment:
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="Not your comment")
    comment.content = content
    await db.commit()
    await db.refresh(comment, attribute_names=["author"])
    return comment


async def delete_comment(
    db: AsyncSession,
    *,
    comment_id: UUID,
    user: User,
) -> None:
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.author_id == user.id:
        await db.delete(comment)
        await db.commit()
        return

    # Allow teacher-owner of the parent course to moderate.
    if user.role == UserRole.teacher:
        owner_id = await db.scalar(
            select(Course.owner_id)
            .join(Module, Module.course_id == Course.id)
            .join(Lesson, Lesson.module_id == Module.id)
            .where(Lesson.id == comment.lesson_id)
        )
        if owner_id == user.id:
            await db.delete(comment)
            await db.commit()
            return

    raise HTTPException(status_code=403, detail="Cannot delete this comment")
