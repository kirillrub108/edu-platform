from redis.asyncio import Redis, from_url

from app.config import settings
from app.constants import REDIS_MAX_CONNECTIONS, REDIS_PUBSUB_MAX_CONNECTIONS

_client: Redis | None = None
# Separate pool for SSE subscriptions — see _get_pubsub_client.
_pubsub_client: Redis | None = None


def _get_client() -> Redis:
    global _client
    if _client is None:
        _client = from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
        )
    return _client


async def get_redis() -> Redis:
    return _get_client()


def _get_pubsub_client() -> Redis:
    """Dedicated pool for pub/sub, kept off the pool everything else shares.

    A subscription holds its connection for the whole life of the SSE stream,
    so streams on the shared pool exhaust it and take auth, session lookups and
    every other Redis-backed path in that worker down with them — measured: the
    21st subscription raises "Too many connections", and so does the next
    unrelated command. Isolating them bounds the damage to the streams.
    """
    global _pubsub_client
    if _pubsub_client is None:
        _pubsub_client = from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=REDIS_PUBSUB_MAX_CONNECTIONS,
        )
    return _pubsub_client


async def get_pubsub_redis() -> Redis:
    """Use for `.pubsub()` only; ordinary commands belong on `get_redis`."""
    return _get_pubsub_client()


async def close_redis() -> None:
    global _client, _pubsub_client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pubsub_client is not None:
        await _pubsub_client.aclose()
        _pubsub_client = None
