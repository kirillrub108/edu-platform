from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import Comment
from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.user import User, UserRole


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
