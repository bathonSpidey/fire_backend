from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class AccountType(StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"
    INVESTMENT = "investment"
    CREDIT_CARD = "credit_card"
    CASH = "cash"


@dataclass
class Account:
    id: UUID
    user_id: UUID
    name: str
    account_type: AccountType
    institution: str | None = None
    last_known_balance: Decimal | None = None
    currency: str = "EUR"
    is_active: bool = True

    @classmethod
    def create(
        cls,
        user_id: UUID,
        name: str,
        account_type: AccountType,
        institution: str | None = None,
        currency: str = "EUR",
    ) -> "Account":
        return cls(
            id=uuid4(),
            user_id=user_id,
            name=name,
            account_type=account_type,
            institution=institution,
            currency=currency,
        )