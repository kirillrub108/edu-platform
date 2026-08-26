from pydantic import BaseModel, ConfigDict


class NotificationSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notify_content: bool
    notify_feedback: bool
    notify_submissions: bool


class NotificationSettingsUpdate(BaseModel):
    """Partial update — an omitted field keeps its current value."""

    notify_content: bool | None = None
    notify_feedback: bool | None = None
    notify_submissions: bool | None = None
