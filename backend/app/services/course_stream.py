"""Process-wide fan-out for the student cabinet's course-access stream.

One Redis subscription per worker instead of one per open browser tab: a single
pattern subscription to `student:*:courses` feeds an in-process registry of
asyncio queues keyed by student id. Redis connections are then O(workers), not
O(open tabs) — the previous shape held a connection for the whole life of every
tab and ran out at the pool ceiling (DECISIONS §62).

The reader survives a Redis hiccup by re-subscribing with backoff rather than
dying: with one reader serving everyone, letting it fail would silently freeze
every open cabinet while the SSE connections still looked healthy.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator
from uuid import UUID

import structlog
from redis.asyncio import Redis

from app.constants import (
    COURSE_STREAM_QUEUE_MAXSIZE,
    COURSE_STREAM_READY_TIMEOUT_SECONDS,
    COURSE_STREAM_RETRY_MAX_SECONDS,
    COURSE_STREAM_RETRY_START_SECONDS,
)

logger = structlog.get_logger()

CHANNEL_PATTERN = "student:*:courses"

_subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
_reader: asyncio.Task[None] | None = None
# Set once the pattern subscription is live; subscribers wait on it so a change
# published right after they connect isn't dropped into the setup window.
_ready: asyncio.Event | None = None


def _student_id_from_channel(channel: str) -> str | None:
    """`student:{id}:courses` → `{id}`; anything else is not ours."""
    parts = channel.split(":")
    if len(parts) == 3 and parts[0] == "student" and parts[2] == "courses":
        return parts[1]
    return None


def _dispatch(channel: str, data: str) -> None:
    student_id = _student_id_from_channel(channel)
    if student_id is None:
        return
    for queue in _subscribers.get(student_id, ()):
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            # The client reacts to any message by refetching its whole list, so
            # a queued message it hasn't read yet already covers this one.
            pass


async def _read_forever(redis: Redis) -> None:
    delay = COURSE_STREAM_RETRY_START_SECONDS
    while True:
        pubsub = redis.pubsub()
        try:
            await pubsub.psubscribe(CHANNEL_PATTERN)
            delay = COURSE_STREAM_RETRY_START_SECONDS
            if _ready is not None:
                _ready.set()
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "pmessage":
                    _dispatch(msg["channel"], msg["data"])
        except asyncio.CancelledError:
            raise
        except Exception:
            if _ready is not None:
                _ready.clear()
            logger.warning("course_stream_reader_retrying", delay_seconds=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, COURSE_STREAM_RETRY_MAX_SECONDS)
        finally:
            try:
                await pubsub.aclose()
            except Exception:
                pass


def _ensure_reader(redis: Redis) -> asyncio.Event:
    global _reader, _ready
    if _reader is None or _reader.done():
        _ready = asyncio.Event()
        _reader = asyncio.create_task(_read_forever(redis))
    assert _ready is not None
    return _ready


def _stop_reader() -> None:
    global _reader, _ready
    _ready = None
    if _reader is not None:
        # Cancel without awaiting — the task tears its own subscription down.
        _reader.cancel()
        _reader = None


def _unregister(key: str, queue: asyncio.Queue[str]) -> None:
    subscribers = _subscribers.get(key)
    if subscribers is not None:
        subscribers.discard(queue)
        if not subscribers:
            _subscribers.pop(key, None)
    if not _subscribers:
        _stop_reader()


@asynccontextmanager
async def subscribe(redis: Redis, student_id: UUID) -> AsyncIterator[asyncio.Queue[str]]:
    """Yields a queue fed with this student's access-change payloads.

    The reader task starts with the first subscriber and stops with the last, so
    an idle worker holds no Redis subscription at all.

    Registration and teardown are deliberately synchronous. This runs inside an
    SSE generator that is CANCELLED when the browser goes away, and an `await`
    in the cleanup path — a contended lock, say — is cancelled along with it,
    leaving the subscriber registered and the reader alive forever (measured:
    500 disconnected clients kept the subscription up indefinitely). The event
    loop is single threaded, so plain dict/set mutation needs no lock.
    """
    key = str(student_id)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=COURSE_STREAM_QUEUE_MAXSIZE)

    _subscribers[key].add(queue)
    ready = _ensure_reader(redis)
    try:
        try:
            await asyncio.wait_for(ready.wait(), timeout=COURSE_STREAM_READY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            # Stream still runs: it may just miss changes until Redis recovers,
            # and the cabinet refetches on tab focus regardless.
            logger.warning("course_stream_not_ready", student_id=key)
        yield queue
    finally:
        _unregister(key, queue)


async def shutdown() -> None:
    """Called from the app lifespan so a worker doesn't leave the task behind.
    Unlike `_stop_reader` this awaits the task, because the loop is about to go
    away and a pending cancellation would never be delivered."""
    global _reader, _ready
    _subscribers.clear()
    task, _reader, _ready = _reader, None, None
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
