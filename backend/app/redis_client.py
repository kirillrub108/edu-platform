from redis.asyncio import Redis, from_url

from app.config import settings

_client: Redis | None = None


def _get_client() -> Redis:
    global _client
    if _client is None:
        _client = from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _client


async def get_redis() -> Redis:
    return _get_client()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
