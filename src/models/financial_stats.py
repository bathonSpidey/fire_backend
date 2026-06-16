from pydantic import BaseModel


class CategorySummary(BaseModel):
    total: float
    percentage_of_total: float


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
