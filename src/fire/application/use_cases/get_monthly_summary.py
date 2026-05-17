from dataclasses import dataclass, field
from decimal import Decimal

from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.domain.interfaces.repositories import ITransactionRepository


@dataclass
class GetMonthlySummaryRequest:
    year: int
    month: int


@dataclass
class MonthlySummary:
    year: int
    month: int
    total_income: Decimal
    total_expenses: Decimal
    net_savings: Decimal
    transaction_count: int
    category_totals: dict[TransactionCategory, Decimal] = field(default_factory=dict)


class GetMonthlySummary:
    """
    Use case: aggregate all transactions for a given month into a
    summary DTO. Pure calculation — no LLM, no file I/O.
    This DTO is what GenerateInsights consumes.
    """

    def __init__(self, transaction_repo: ITransactionRepository) -> None:
        self._transaction_repo = transaction_repo

    async def execute(self, request: GetMonthlySummaryRequest) -> MonthlySummary:
        transactions = await self._transaction_repo.get_by_month(request.year, request.month)

        total_income = Decimal("0")
        total_expenses = Decimal("0")
        category_totals: dict[TransactionCategory, Decimal] = {}

        for tx in transactions:
            if tx.transaction_type == TransactionType.CREDIT:
                total_income += tx.amount
            else:
                total_expenses += tx.amount
                category_totals[tx.category] = (
                    category_totals.get(tx.category, Decimal("0")) + tx.amount
                )

        return MonthlySummary(
            year=request.year,
            month=request.month,
            total_income=total_income,
            total_expenses=total_expenses,
            net_savings=total_income - total_expenses,
            transaction_count=len(transactions),
            category_totals=category_totals,
        )
