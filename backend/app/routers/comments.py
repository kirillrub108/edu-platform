from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_lesson_access
from app.limiter import limiter
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.comment import (
    CommentCreate,
    CommentListResponse,
    CommentRead,
    CommentUpdate,
)
from app.services import comment_service

router = APIRouter(prefix="/api/v1", tags=["comments"])


@router.get(
    "/lessons/{lesson_id}/comments",
    response_model=CommentListResponse,
)
async def list_lesson_comments(
    lesson_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
) -> CommentListResponse:
    items, total = await comment_service.list_comments(
        db, lesson_id, limit=limit, offset=offset
    )
    return CommentListResponse(
        items=[CommentRead.model_validate(c) for c in items],
        total=total,
    )


@router.post(
    "/lessons/{lesson_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_lesson_comment(
    request: Request,
    lesson_id: UUID,
    data: CommentCreate,
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
) -> CommentRead:
    user, _lesson, _is_owner = access
    comment = await comment_service.create_comment(
        db, lesson_id=lesson_id, author_id=user.id, content=data.content
    )
    return CommentRead.model_validate(comment)


@router.patch("/comments/{comment_id}", response_model=CommentRead)
@limiter.limit("30/minute")
async def update_lesson_comment(
    request: Request,
    comment_id: UUID,
    data: CommentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommentRead:
    comment = await comment_service.update_comment(
        db, comment_id=comment_id, user_id=user.id, content=data.content
    )
    return CommentRead.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson_comment(
    comment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await comment_service.delete_comment(db, comment_id=comment_id, user=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
