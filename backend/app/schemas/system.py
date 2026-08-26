from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MaintenanceWindowOut(BaseModel):
    """An announced maintenance window, always in UTC."""

    start: datetime
    end: datetime
    #: Optional operator note. Empty string = show the default copy.
    message: str
    #: True once the window has opened — the banner switches from "planned" to
    #: "in progress" without needing a second request.
    is_active: bool


class SystemStatusOut(BaseModel):
    """Public, unauthenticated system status.

    Deliberately cheap and free of user data: the SPA calls it on every page
    load. `status` stays "ok" — if the backend is down the SPA never gets a body
    at all, and planned downtime is signalled by nginx's fixed
    {"code": "maintenance"} 503 instead.
    """

    status: Literal["ok"] = "ok"
    version: str
    server_time: datetime
    maintenance: MaintenanceWindowOut | None = None
