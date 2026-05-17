from dataclasses import dataclass

from src.fire.application.use_cases.get_monthly_summary import MonthlySummary
from src.fire.domain.entities.budget_insight import BudgetInsight, SpendingBreakdown
from src.fire.domain.interfaces.repositories import IInsightRepository
from src.fire.domain.interfaces.services import ILLMInsightGenerator


@dataclass
class GenerateInsightsRequest:
    summary: MonthlySummary
    fire_progress_note: str | None = None


class GenerateInsights:
    """
    Use case: take a MonthlySummary DTO, ask the LLM for a human-readable
    analysis and tips, build a BudgetInsight entity, and persist it.
    Re-running for the same month overwrites the previous insight.
    """

    def __init__(
        self,
        insight_repo: IInsightRepository,
        llm_generator: ILLMInsightGenerator,
    ) -> None:
        self._insight_repo = insight_repo
        self._llm_generator = llm_generator

    async def execute(self, request: GenerateInsightsRequest) -> BudgetInsight:
        summary = request.summary

        category_totals_str = {cat.value: amount for cat, amount in summary.category_totals.items()}

        llm_summary, llm_tips = await self._llm_generator.generate_monthly_insight(
            year=summary.year,
            month=summary.month,
            total_income=summary.total_income,
            total_expenses=summary.total_expenses,
            category_totals=category_totals_str,
        )

        breakdown = [
            SpendingBreakdown(
                category=cat.value,
                total=amount,
                transaction_count=0,
                percentage_of_spend=(
                    (amount / summary.total_expenses * 100) if summary.total_expenses > 0 else 0
                ),
            )
            for cat, amount in summary.category_totals.items()
        ]

        insight = BudgetInsight.create(
            year=summary.year,
            month=summary.month,
            total_income=summary.total_income,
            total_expenses=summary.total_expenses,
            spending_breakdown=breakdown,
            llm_summary=llm_summary,
            llm_tips=llm_tips,
            fire_progress_note=request.fire_progress_note,
        )

        return await self._insight_repo.save(insight)
