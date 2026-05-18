from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from fire.domain.entities.transaction import TransactionCategory, TransactionType


class TransactionResponse(BaseModel):
    id: UUID
    user_id: UUID
    document_id: UUID
    date: date
    description: str
    amount: Decimal
    transaction_type: TransactionType
    category: TransactionCategory
    merchant: str | None = None
    notes: str | None = None
    is_recurring: bool

    model_config = {"from_attributes": True}


class PatchTransactionRequest(BaseModel):
    """
    All fields optional — send only what you want to change.
    This is how users correct extraction errors.
    """

    amount: Decimal | None = Field(default=None, gt=0)
    transaction_type: TransactionType | None = None
    category: TransactionCategory | None = None
    description: str | None = Field(default=None, min_length=1)
    merchant: str | None = None
    notes: str | None = None
    is_recurring: bool | None = None
