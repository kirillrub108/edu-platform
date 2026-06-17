"""Validated views over the YooKassa payment object (the JSON returned by
POST /payments and GET /payments/{id}). extra="ignore" so new provider fields
never break parsing; only `id`/`status` are required — `confirmation` and its
url are optional, since a captured payment carries no confirmation block.
Domain status mapping (succeeded/canceled) is done by callers over `status`.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict


class YooKassaAmount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str
    currency: str


class YooKassaConfirmation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    confirmation_url: str | None = None
    return_url: str | None = None


class YooKassaPaymentMethod(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    id: str | None = None
    saved: bool | None = None
    title: str | None = None


class YooKassaPayment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: str
    paid: bool | None = None
    amount: YooKassaAmount | None = None
    confirmation: YooKassaConfirmation | None = None
    payment_method: YooKassaPaymentMethod | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
