"""Pub/sub runs on its own connection pool, isolated from everything else.

An SSE subscription holds its Redis connection for as long as the browser tab
stays open. On the shared pool that starves it: measured on redis-py 5.2.1 with
`max_connections=20`, the 21st subscription raises "Too many connections" — and
so does the next unrelated command, which means auth, session lookups and every
other Redis-backed path in that worker start failing too. See DECISIONS §62.
"""

from __future__ import annotations

import pytest

import app.redis_client as redis_client
from app.constants import REDIS_MAX_CONNECTIONS, REDIS_PUBSUB_MAX_CONNECTIONS
from app.redis_client import get_pubsub_redis, get_redis

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """`from_url` is lazy — no socket is opened — but it does parse the URL, and
    the unit env has no valid REDIS_URL. Give it one and clear the module
    singletons so each test builds its own pair; monkeypatch puts both back.
    """
    monkeypatch.setattr(redis_client.settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(redis_client, "_pubsub_client", None)


async def test_pubsub_pool_is_separate_from_the_shared_pool() -> None:
    shared = await get_redis()
    pubsub = await get_pubsub_redis()

    assert shared is not pubsub
    assert shared.connection_pool is not pubsub.connection_pool


async def test_pools_are_sized_from_constants() -> None:
    shared = await get_redis()
    pubsub = await get_pubsub_redis()

    assert shared.connection_pool.max_connections == REDIS_MAX_CONNECTIONS
    assert pubsub.connection_pool.max_connections == REDIS_PUBSUB_MAX_CONNECTIONS
    # The stream pool must be the larger one — it is the one that holds
    # connections open, and it must not be the scarce resource.
    assert REDIS_PUBSUB_MAX_CONNECTIONS > REDIS_MAX_CONNECTIONS


async def test_clients_are_singletons_per_process() -> None:
    """Both are module-level singletons; a fresh client per request would defeat
    the pooling entirely."""
    assert await get_redis() is await get_redis()
    assert await get_pubsub_redis() is await get_pubsub_redis()
