"""Data contracts for statements read by Claude (bank statements and PayPal exports)."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class Bank(StrEnum):
    SPARKASSE = "Sparkasse"
    N26 = "N26"
    COMMERZBANK = "Commerzbank"
    PAYPAL = "PayPal"


class TxKind(StrEnum):
    SPEND = "spend"  # money out for goods/services
    INCOME = "income"  # salary and other real income
    INTERNAL_TRANSFER = "internal_transfer"  # between the household's own accounts/PayPal
    INVESTMENT = "investment"  # broker, ETF savings plan, securities
    FEE = "fee"  # bank fees
    CASH = "cash"  # ATM withdrawals / deposits
    REFUND = "refund"  # money back from a merchant or tax office
    OTHER = "other"


class StatementLine(BaseModel):
    booking_date: date = Field(description="Booking date as printed at the start of the entry")
    purchase_date: date | None = Field(
        default=None,
        description="Real purchase day when the text reveals it (e.g. Bluecode/card payments "
        "booked days later). Null otherwise.",
    )
    amount: float = Field(description="Negative = money out of the account, positive = money in")
    counterparty: str = Field(
        description="Clean short name of who was paid / who paid: 'Kaufland', 'Netflix', "
        "'Deutsche Lufthansa', 'Fitness Forum Baden-Baden'. For PayPal debits the real "
        "merchant, not 'PayPal Europe'."
    )
    description: str = Field(
        description="The entry's text, whitespace-normalised, without inventing or dropping facts"
    )
    channel: str | None = Field(
        default=None, description="SEPA | Card | Bluecode | PayPal | Standing order | Cash | Fee"
    )
    payment_reference: str | None = Field(
        default=None,
        description="Identifier usable to match other documents: Bluecode ID/transaction code, "
        "PayPal transaction number, invoice number. Null if none.",
    )
    kind: TxKind
    category: str | None = Field(
        default=None, description="Spending category from the rules list; null for non-spend"
    )


class StatementSubmission(BaseModel):
    bank: Bank
    period_start: date = Field(description="First day covered by this statement")
    period_end: date = Field(description="Last day covered by this statement")
    opening_balance: float | None = Field(
        default=None, description="Balance at the start (Sparkasse: 'Kontostand am ...' at top)"
    )
    closing_balance: float | None = Field(
        default=None, description="Balance at the end of the period"
    )
    transactions: list[StatementLine]
