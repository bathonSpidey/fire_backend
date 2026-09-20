from pydantic import BaseModel


class CategorySummary(BaseModel):
    total: float
    percentage_of_total: float
    # Describes the category so the frontend never has to guess from its name
    flow: str | None = None  # income | expense | investment
    label: str | None = None
    group: str | None = None
    fixed: bool = False


class StatsSources(BaseModel):
    """What a month's numbers are built from, so the page can say so."""

    statements: list[str] = []  # banks whose statement is uploaded for the month
    receipts: int = 0  # receipts dated in the month


class MonthlyStatsResponse(BaseModel):
    month: str
    year: int
    gross_income: float
    lifestyle_expenses: float
    net_savings: float
    savings_rate_pct: float
    total_invested: float
    fixed_vs_variable_ratio: str  # e.g., "40% Fixed / 60% Variable"
    categories: dict[str, CategorySummary]
    sources: StatsSources | None = None


class PeriodStatsResponse(BaseModel):
    """The formal schema returned by your rolling-range engine."""

    period_months_count: int
    gross_income: float
    lifestyle_expenses: float
    net_savings: float
    savings_rate_pct: float
    total_invested: float
    fixed_vs_variable_ratio: str
    categories: dict[str, CategorySummary]
