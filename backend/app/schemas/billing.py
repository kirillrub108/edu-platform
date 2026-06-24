from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.credit import CreditOperation
from app.models.payment import PaymentStatus


class TrialOut(BaseModel):
    lectures_used: int
    lectures_limit: int
    quizzes_used: int
    quizzes_limit: int


class BalanceOut(BaseModel):
    balance: int
    reserved: int
    available: int
    plan: str
    trial: TrialOut


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delta: int
    operation: CreditOperation
    ref_id: str | None
    description: str | None
    created_at: datetime


class VideoPricingOut(BaseModel):
    """Formula parameters for video generation — the frontend renders the
    human-readable cost rule and examples from these instead of hardcoding."""

    text_base: int
    auto_base: int
    chars_per_credit: int
    auto_chars_per_slide: int


class PlansOut(BaseModel):
    weights: dict[str, int]
    plans: dict[str, dict[str, int]]
    # Package values are mixed (title/payment_subject/payment_mode are str,
    # credits/price_rub/vat_code are int) — see constants.CREDIT_PACKAGES.
    packages: dict[str, dict[str, str | int]]
    video_pricing: VideoPricingOut


class PaymentCreateRequest(BaseModel):
    package_key: str


class PaymentCreateOut(BaseModel):
    payment_id: UUID
    confirmation_url: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_key: str
    amount_rub: Decimal
    credits: int
    status: PaymentStatus
    created_at: datetime


class EstimateVideoOut(BaseModel):
    mode: str  # 'auto' | 'text'
    slides: int | None
    script_chars: int
    credits: int | None  # None when slides are unknown (no PPTX yet)


class EstimateTrialOut(BaseModel):
    lectures_used: int
    lectures_limit: int
    quizzes_used: int
    quizzes_limit: int
    video_trial_available: bool
    quiz_trial_available: bool


class GenerationEstimateOut(BaseModel):
    video: EstimateVideoOut
    vision_credits: int
    quiz_credits: int
    ai_review_credits: int
    available: int
    plan: str
    trial: EstimateTrialOut


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
    # Post-grant balance so callers (top-up flow) can update without a refetch.
    balance: int
    reserved: int
    available: int


class RenewalOut(BaseModel):
    renewed_accounts: int
