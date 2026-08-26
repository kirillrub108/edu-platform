"""Regression: the SSE presence marker must survive the terminal event.

The video pipeline enqueues the "lesson ready" notification and then publishes
the terminal SSE event. The stream stops on that event — if its teardown cleared
presence immediately, the notification task (which runs a fraction of a second
later, on another worker) would always read "nobody watching" and the gate would
never fire for the one case it exists for.

A client that goes away *before* the job finishes must still clear presence at
once, otherwise closing the tab would silently suppress the mail.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import LessonStatus
from app.models.user import User
from app.services.notification_service import presence_key
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration

# Hard ceiling so a mis-wired stream fails the test instead of hanging the suite.
_STREAM_TIMEOUT = 10.0


async def _fake_redis(app):
    from app.redis_client import get_redis

    return await app.dependency_overrides[get_redis]()


async def _generating_lesson(db: AsyncSession, teacher: User):
    """A lesson with a live video task — that's what makes progress_stream take
    the live pub/sub path instead of replaying a terminal snapshot."""
    course = await make_course(db, teacher)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module)
    lesson.status = LessonStatus.processing
    lesson.video_task_id = str(uuid4())
    await db.commit()
    return lesson


async def _members(redis, lesson_id) -> int:
    return int(await redis.zcard(presence_key(str(lesson_id))))


async def _await_members(redis, lesson_id, expected: int) -> None:
    while await _members(redis, lesson_id) != expected:
        await asyncio.sleep(0.05)


async def test_presence_survives_the_terminal_event(
    app,
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    lesson = await _generating_lesson(db_session, teacher_user)
    redis = await _fake_redis(app)

    async def publish_terminal() -> None:
        # Wait for the stream to register presence, then end the job the way the
        # pipeline does.
        await _await_members(redis, lesson.id, 1)
        await redis.publish(
            f"lesson:{lesson.id}",
            json.dumps({"status": "published", "video_url": "/files/v.mp4"}),
        )

    async def drain() -> None:
        async with client.stream(
            "GET", f"/api/v1/lessons/{lesson.id}/progress-stream", cookies=teacher_token
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    await asyncio.wait_for(asyncio.gather(drain(), publish_terminal()), timeout=_STREAM_TIMEOUT)

    # The stream is over, but the owner watched it finish — presence must still
    # be readable by the notification task that the pipeline just enqueued.
    assert await _members(redis, lesson.id) == 1


async def test_presence_is_cleared_when_the_client_goes_away_first(
    app,
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    lesson = await _generating_lesson(db_session, teacher_user)
    redis = await _fake_redis(app)

    async def stream_forever() -> None:
        async with client.stream(
            "GET", f"/api/v1/lessons/{lesson.id}/progress-stream", cookies=teacher_token
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    task = asyncio.create_task(stream_forever())
    try:
        await asyncio.wait_for(_await_members(redis, lesson.id, 1), timeout=_STREAM_TIMEOUT)
        # Cancelling the request task is what a dropped connection looks like to
        # the generator: it raises through the yield straight into `finally`.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()

    await asyncio.wait_for(_await_members(redis, lesson.id, 0), timeout=_STREAM_TIMEOUT)
