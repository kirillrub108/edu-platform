from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.credit import CreditOperation


class BalanceOut(BaseModel):
    balance: int
    reserved: int
    available: int
    plan: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delta: int
    operation: CreditOperation
    ref_id: str | None
    description: str | None
    created_at: datetime


class PlansOut(BaseModel):
    weights: dict[str, int]
    plans: dict[str, dict[str, int]]
    topup_packs: list[dict[str, int]]


class GrantRequest(BaseModel):
    user_id: UUID
    amount: int = Field(gt=0)
    description: str = "Manual admin grant"


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    delta: int
    created_at: datetime


class RenewalOut(BaseModel):
    renewed_accounts: int
