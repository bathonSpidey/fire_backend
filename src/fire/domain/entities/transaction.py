from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class TransactionType(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class TransactionCategory(StrEnum):
    GROCERIES = "groceries"
    DINING = "dining"
    TRANSPORT = "transport"
    HOUSING = "housing"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    INCOME = "income"
    INVESTMENT = "investment"
    SAVINGS = "savings"
    TRANSFER = "transfer"
    OTHER = "other"


@dataclass
class Transaction:
    id: UUID
    user_id: UUID
    document_id: UUID
    account_id: UUID | None
    date: Date
    description: str
    amount: Decimal
    transaction_type: TransactionType
    category: TransactionCategory
    merchant: str | None = None
    notes: str | None = None
    is_recurring: bool = False
    # Phase 1 — receipt attachment
    parent_transaction_id: UUID | None = None  # receipt items point to bank debit
    receipt_document_id: UUID | None = None  # bank debit has receipt attached

    @classmethod
    def create(
        cls,
        user_id: UUID,
        document_id: UUID,
        date: Date,
        description: str,
        amount: Decimal,
        transaction_type: TransactionType,
        category: TransactionCategory = TransactionCategory.OTHER,
        account_id: UUID | None = None,
        merchant: str | None = None,
        parent_transaction_id: UUID | None = None,
    ) -> "Transaction":
        if amount < Decimal("0"):
            raise ValueError("Amount must be non-negative. Use transaction_type for direction.")
        return cls(
            id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            account_id=account_id,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
            category=category,
            merchant=merchant,
            parent_transaction_id=parent_transaction_id,
        )

    @property
    def is_receipt_item(self) -> bool:
        """True when this transaction is a receipt line item, not a top-level bank entry."""
        return self.parent_transaction_id is not None

    @property
    def signed_amount(self) -> Decimal:
        if self.transaction_type == TransactionType.DEBIT:
            return -self.amount
        return self.amount
