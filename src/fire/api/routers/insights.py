from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from src.fire.api.dependencies import (
    get_generate_insights_use_case,
    get_insight_repo,
    get_monthly_summary_use_case,
)
from src.fire.api.schemas.insight import GenerateInsightRequest, InsightResponse
from src.fire.application.use_cases.generate_insights import (
    GenerateInsights,
    GenerateInsightsRequest,
)
from src.fire.application.use_cases.get_monthly_summary import (
    GetMonthlySummary,
    GetMonthlySummaryRequest,
)
from src.fire.domain.entities.budget_insight import BudgetInsight
from src.fire.infrastructure.repositories.account_insight_repositories import InsightRepository

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("/generate", response_model=InsightResponse)
async def generate_insight(
    user_id: UUID,
    year: int,
    month: int,
    request: GenerateInsightRequest,
    summary_use_case: GetMonthlySummary = Depends(get_monthly_summary_use_case),
    generate_use_case: GenerateInsights = Depends(get_generate_insights_use_case),
) -> InsightResponse:
    """
    Generates a monthly insight using the configured LLM.
    Re-running overwrites the previous insight for the same month.
    """
    summary = await summary_use_case.execute(
        GetMonthlySummaryRequest(user_id=user_id, year=year, month=month)
    )
    insight = await generate_use_case.execute(
        GenerateInsightsRequest(
            summary=summary,
            fire_progress_note=request.fire_progress_note,
        )
    )
    return _to_response(insight)


@router.get("", response_model=InsightResponse)
async def get_insight(
    user_id: UUID,
    year: int,
    month: int,
    insight_repo: InsightRepository = Depends(get_insight_repo),
) -> InsightResponse:
    insight = await insight_repo.get_by_user_and_month(user_id, year, month)
    if not insight:
        raise HTTPException(
            status_code=404,
            detail=f"No insight found for {year}-{month:02d}. Use POST /insights/generate first.",
        )
    return _to_response(insight)


@router.get("/history", response_model=list[InsightResponse])
async def list_insights(
    user_id: UUID,
    limit: int = 12,
    insight_repo: InsightRepository = Depends(get_insight_repo),
) -> list[InsightResponse]:
    insights = await insight_repo.list_by_user(user_id, limit=limit)
    return [_to_response(i) for i in insights]


def _to_response(insight: BudgetInsight) -> InsightResponse:
    from fire.api.schemas.insight import SpendingBreakdownResponse

    return InsightResponse(
        id=insight.id,
        user_id=insight.user_id,
        year=insight.year,
        month=insight.month,
        total_income=insight.total_income,
        total_expenses=insight.total_expenses,
        net_savings=insight.net_savings,
        savings_rate=insight.savings_rate,
        spending_breakdown=[
            SpendingBreakdownResponse(
                category=b.category,
                total=b.total,
                transaction_count=b.transaction_count,
                percentage_of_spend=b.percentage_of_spend,
            )
            for b in insight.spending_breakdown
        ],
        llm_summary=insight.llm_summary,
        llm_tips=insight.llm_tips,
        generated_at=insight.generated_at,
        fire_progress_note=insight.fire_progress_note,
    )
