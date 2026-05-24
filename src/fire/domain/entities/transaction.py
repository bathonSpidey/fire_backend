from dataclasses import dataclass, field
from datetime import date as Date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class TransactionType(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"
    TRANSFER = "transfer"  # money moved to investment account — excluded from expense totals


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
    # Receipt attachment
    parent_transaction_id: UUID | None = None
    receipt_document_id: UUID | None = None
    # Transfer / investment account attachment
    transfer_account_name: str | None = None  # e.g. "N26", "Commerzbank"
    transfer_document_id: UUID | None = None  # the attached investment PDF
    is_investment_item: bool = False  # came from an attached bank statement

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
        transfer_account_name: str | None = None,
        is_investment_item: bool = False,
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
            transfer_account_name=transfer_account_name,
            is_investment_item=is_investment_item,
        )

    @property
    def is_receipt_item(self) -> bool:
        return self.parent_transaction_id is not None

    @property
    def is_transfer(self) -> bool:
        return self.transaction_type == TransactionType.TRANSFER

    @property
    def signed_amount(self) -> Decimal:
        if self.transaction_type == TransactionType.DEBIT:
            return -self.amount
        return self.amount
