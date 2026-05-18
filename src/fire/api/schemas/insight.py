from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SpendingBreakdownResponse(BaseModel):
    category: str
    total: Decimal
    transaction_count: int
    percentage_of_spend: Decimal


class InsightResponse(BaseModel):
    id: UUID
    user_id: UUID
    year: int
    month: int
    total_income: Decimal
    total_expenses: Decimal
    net_savings: Decimal
    savings_rate: Decimal
    spending_breakdown: list[SpendingBreakdownResponse]
    llm_summary: str
    llm_tips: list[str]
    generated_at: datetime
    fire_progress_note: str | None = None

    model_config = {"from_attributes": True}


class GenerateInsightRequest(BaseModel):
    fire_progress_note: str | None = None
