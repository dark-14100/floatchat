"""Shared SlowAPI limiter instance for backend routers."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def get_rate_limit_key(request) -> str:
	"""Prefer auth identity for rate limiting, fallback to client address."""
	identity = getattr(request.state, "rate_limit_key", None)
	if identity:
		return str(identity)
	return get_remote_address(request)


limiter = Limiter(
	key_func=get_rate_limit_key,
	storage_uri=settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL,
)
