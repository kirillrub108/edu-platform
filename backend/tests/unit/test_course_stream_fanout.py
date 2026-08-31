"""One Redis subscription per worker, not one per open tab (DECISIONS §62).

These pin the properties the fan-out exists for: the reader count stays flat as
clients pile on, each student only sees their own events, and the reader is torn
down when the last client leaves so an idle worker holds nothing. The module
internals (`_reader`, `_subscribers`) are asserted directly — they *are* the
invariant here, and nothing else exposes it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import AsyncExitStack
from typing import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.constants import COURSE_STREAM_QUEUE_MAXSIZE
from app.services import course_access_service, course_stream

pytestmark = pytest.mark.unit

FakeRedis = fakeredis.aioredis.FakeRedis

# The reader polls with timeout=1.0, so allow a couple of poll cycles.
_DELIVERY_TIMEOUT = 5.0


@pytest_asyncio.fixture()
async def fake_redis() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        # Never leave a reader task behind for the next test.
        await course_stream.shutdown()
        await client.aclose()


async def _publish(client: FakeRedis, student_id: uuid.UUID, event: str) -> None:
    """Publish exactly the way the grant endpoints do."""
    await client.publish(
        course_access_service.courses_channel(student_id),
        json.dumps({"event": event, "course_id": str(uuid.uuid4())}),
    )


async def test_subscriber_receives_its_own_events(fake_redis: FakeRedis) -> None:
    student = uuid.uuid4()
    async with course_stream.subscribe(fake_redis, student) as queue:
        await _publish(fake_redis, student, "granted")
        payload = await asyncio.wait_for(queue.get(), timeout=_DELIVERY_TIMEOUT)

    assert json.loads(payload)["event"] == "granted"


async def test_events_do_not_leak_between_students(fake_redis: FakeRedis) -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    async with course_stream.subscribe(fake_redis, mine) as my_queue:
        async with course_stream.subscribe(fake_redis, theirs) as their_queue:
            await _publish(fake_redis, theirs, "granted")
            await asyncio.wait_for(their_queue.get(), timeout=_DELIVERY_TIMEOUT)

            assert my_queue.empty()


async def test_two_tabs_of_one_student_both_get_the_event(fake_redis: FakeRedis) -> None:
    student = uuid.uuid4()
    async with course_stream.subscribe(fake_redis, student) as first:
        async with course_stream.subscribe(fake_redis, student) as second:
            await _publish(fake_redis, student, "revoked")

            assert await asyncio.wait_for(first.get(), timeout=_DELIVERY_TIMEOUT)
            assert await asyncio.wait_for(second.get(), timeout=_DELIVERY_TIMEOUT)


async def test_many_subscribers_share_one_reader(fake_redis: FakeRedis) -> None:
    """The whole point: Redis work is O(workers), not O(open tabs)."""
    students = [uuid.uuid4() for _ in range(25)]

    async with AsyncExitStack() as stack:
        for student in students:
            await stack.enter_async_context(course_stream.subscribe(fake_redis, student))

        reader = course_stream._reader
        assert reader is not None and not reader.done()
        assert len(course_stream._subscribers) == len(students)


async def test_reader_stops_with_the_last_subscriber(fake_redis: FakeRedis) -> None:
    student = uuid.uuid4()
    async with course_stream.subscribe(fake_redis, student):
        assert course_stream._reader is not None

    assert course_stream._reader is None
    assert course_stream._subscribers == {}


async def test_slow_client_does_not_grow_without_bound(fake_redis: FakeRedis) -> None:
    """Overflow is dropped on purpose — the client refetches its whole list on
    any message, so a message it hasn't read yet already covers the dropped
    ones. What matters is that the queue cannot grow without bound."""
    student = uuid.uuid4()
    async with course_stream.subscribe(fake_redis, student) as queue:
        for _ in range(COURSE_STREAM_QUEUE_MAXSIZE + 10):
            course_stream._dispatch(f"student:{student}:courses", '{"event":"granted"}')

        assert queue.qsize() == COURSE_STREAM_QUEUE_MAXSIZE
