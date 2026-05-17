from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass
class SpendingBreakdown:
    category: str
    total: Decimal
    transaction_count: int
    percentage_of_spend: Decimal


@dataclass
class BudgetInsight:
    id: UUID
    user_id: UUID
    year: int
    month: int
    total_income: Decimal
    total_expenses: Decimal
    net_savings: Decimal
    savings_rate: Decimal
    spending_breakdown: list[SpendingBreakdown]
    llm_summary: str
    llm_tips: list[str]
    generated_at: datetime
    fire_progress_note: str | None = None

    @classmethod
    def create(
        cls,
        user_id: UUID,
        year: int,
        month: int,
        total_income: Decimal,
        total_expenses: Decimal,
        spending_breakdown: list[SpendingBreakdown],
        llm_summary: str,
        llm_tips: list[str],
        fire_progress_note: str | None = None,
    ) -> "BudgetInsight":
        net_savings = total_income - total_expenses
        savings_rate = (
            (net_savings / total_income * Decimal("100"))
            if total_income > Decimal("0")
            else Decimal("0")
        )
        return cls(
            id=uuid4(),
            user_id=user_id,
            year=year,
            month=month,
            total_income=total_income,
            total_expenses=total_expenses,
            net_savings=net_savings,
            savings_rate=savings_rate.quantize(Decimal("0.01")),
            spending_breakdown=spending_breakdown,
            llm_summary=llm_summary,
            llm_tips=llm_tips,
            generated_at=datetime.now(UTC),
            fire_progress_note=fire_progress_note,
        )
