"""Owner «view as student» preview: GET /api/v1/courses/{id}/preview.

The endpoint returns the FULL module/lesson tree (drafts included) where every
node carries its effective student visibility (visibility_service AND-rule).
It is owner-only — any non-owner gets 404 so the course's existence is never
revealed — and strictly read-only: no rows written, no Celery tasks enqueued.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import AssignmentSubmission
from app.models.enrollment import Enrollment, LessonProgress
from app.models.quiz import QuizAttempt
from app.models.user import User
from tests.conftest import _bearer
from tests.factories import (
    make_assignment,
    make_course,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_question,
)

pytestmark = pytest.mark.integration


async def _make_second_teacher(db_session: AsyncSession) -> User:
    import uuid

    from app.models.user import UserRole
    from app.services.auth_service import hash_password

    user = User(
        email=f"teacher2-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("teacher2-pass-123"),
        full_name="Teacher Two",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_owner_gets_full_tree_with_effective_visibility(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=False)
    pub_module = await make_module(db_session, course, is_published=True, order=0)
    visible_lesson = await make_lesson(db_session, pub_module, is_published=True)
    draft_lesson = await make_lesson(
        db_session, pub_module, is_published=False, order=1
    )
    draft_module = await make_module(db_session, course, is_published=False, order=1)
    # Published lesson inside a draft module → effectively invisible.
    orphaned_lesson = await make_lesson(db_session, draft_module, is_published=True)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/preview", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(course.id)
    assert body["is_published"] is False

    modules = {m["id"]: m for m in body["modules"]}
    # Drafts are NOT pruned — the whole tree is returned.
    assert set(modules) == {str(pub_module.id), str(draft_module.id)}

    pub = modules[str(pub_module.id)]
    assert pub["visible_to_student"] is True
    lessons = {lesson["id"]: lesson for lesson in pub["lessons"]}
    assert lessons[str(visible_lesson.id)]["visible_to_student"] is True
    assert lessons[str(draft_lesson.id)]["visible_to_student"] is False

    draft = modules[str(draft_module.id)]
    assert draft["visible_to_student"] is False
    # Effective visibility: published lesson under a draft module is hidden.
    assert draft["lessons"][0]["id"] == str(orphaned_lesson.id)
    assert draft["lessons"][0]["visible_to_student"] is False


async def test_empty_course_returns_empty_tree(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/preview", cookies=teacher_token
    )
    assert resp.status_code == 200
    assert resp.json()["modules"] == []


async def test_foreign_teacher_gets_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    other = await _make_second_teacher(db_session)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/preview", cookies=_bearer(other)
    )
    assert resp.status_code == 404


async def test_student_gets_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/preview", cookies=student_token
    )
    assert resp.status_code == 404


async def test_anonymous_gets_401(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    course = await make_course(db_session, owner=teacher_user)

    resp = await client.get(f"/api/v1/courses/{course.id}/preview")
    assert resp.status_code == 401


async def test_preview_reads_have_no_side_effects(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview flow (tree + owner lesson + quiz-with-answers + assignments)
    writes nothing and enqueues no Celery tasks."""
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=True)
    quiz = await make_quiz(db_session, lesson, published=True)
    await make_quiz_question(db_session, quiz)
    await make_assignment(db_session, lesson, published=True)

    import celery.app.task as celery_task_mod

    enqueued: list[str] = []

    def _spy_apply_async(self: Any, *args: Any, **kwargs: Any) -> None:
        enqueued.append(self.name)

    monkeypatch.setattr(celery_task_mod.Task, "apply_async", _spy_apply_async)

    async def _counts() -> dict[str, int]:
        out: dict[str, int] = {}
        for model in (Enrollment, LessonProgress, QuizAttempt, AssignmentSubmission):
            out[model.__name__] = (
                await db_session.scalar(select(func.count()).select_from(model))
            ) or 0
        return out

    before = await _counts()

    for url in (
        f"/api/v1/courses/{course.id}/preview",
        f"/api/v1/lessons/{lesson.id}",
        f"/api/v1/lessons/{lesson.id}/quiz",
        f"/api/v1/lessons/{lesson.id}/quiz/questions",
        f"/api/v1/lessons/{lesson.id}/assignments",
    ):
        resp = await client.get(url, cookies=teacher_token)
        assert resp.status_code == 200, url

    assert await _counts() == before
    assert enqueued == []
