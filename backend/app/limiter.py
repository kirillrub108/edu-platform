from slowapi import Limiter
from slowapi.util import get_remote_address

# Global 60/minute applies to all routes; per-route stricter limits also apply
# (slowapi enforces both independently — the tighter one fires first).
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
