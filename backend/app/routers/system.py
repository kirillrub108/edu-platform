from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.schemas.system import MaintenanceWindowOut, SystemStatusOut
from app.services.system_service import maintenance_window

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status", response_model=SystemStatusOut)
async def system_status() -> SystemStatusOut:
    """Public status probe used by the SPA's maintenance banner.

    No auth, no database, no Redis — it must stay answerable while the rest of
    the stack is being rolled. See docs/DECISIONS.md §53.
    """
    window = maintenance_window()
    return SystemStatusOut(
        version=settings.APP_VERSION,
        server_time=datetime.now(timezone.utc),
        maintenance=(
            MaintenanceWindowOut(
                start=window.start,
                end=window.end,
                message=window.message,
                is_active=window.is_active,
            )
            if window is not None
            else None
        ),
    )
