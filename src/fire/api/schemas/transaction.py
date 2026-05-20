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
    amount: Decimal = Field(
        examples=[Decimal("42.50")],
        description="Transaction amount, always positive.",
    )
    transaction_type: TransactionType
    category: TransactionCategory
    merchant: str | None = None
    notes: str | None = None
    is_recurring: bool
    parent_transaction_id: UUID | None = None
    receipt_document_id: UUID | None = None
    is_receipt_item: bool = False

    model_config = {"from_attributes": True}


class PatchTransactionRequest(BaseModel):
    """All fields optional — send only what you want to change."""

    amount: Decimal | None = Field(
        default=None,
        gt=0,
        examples=[Decimal("42.50")],
    )
    transaction_type: TransactionType | None = None
    category: TransactionCategory | None = None
    description: str | None = Field(default=None, min_length=1)
    merchant: str | None = None
    notes: str | None = None
    is_recurring: bool | None = None
