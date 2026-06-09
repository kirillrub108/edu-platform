from pydantic import BaseModel


class ResourceQuotaRead(BaseModel):
    used: int
    limit: int
    remaining: int


class QuotaStatusRead(BaseModel):
    tier: str
    period_key: str
    video: ResourceQuotaRead
    vision: ResourceQuotaRead
    max_concurrent_jobs: int
    active_jobs: int
