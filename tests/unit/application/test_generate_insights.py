from decimal import Decimal
from uuid import uuid4

import pytest
from src.fire.application.use_cases.generate_insights import (
    GenerateInsights,
    GenerateInsightsRequest,
)
from src.fire.application.use_cases.get_monthly_summary import MonthlySummary
from src.fire.domain.entities.transaction import TransactionCategory

from tests.fakes import FakeInsightRepository, FakeLLMInsightGenerator

USER_ID = uuid4()


def _make_summary(**kwargs) -> MonthlySummary:
    defaults = dict(
        user_id=USER_ID,
        year=2024,
        month=1,
        total_income=Decimal("3000"),
        total_expenses=Decimal("1800"),
        net_savings=Decimal("1200"),
        transaction_count=20,
        category_totals={
            TransactionCategory.GROCERIES: Decimal("400"),
            TransactionCategory.DINING: Decimal("200"),
        },
    )
    return MonthlySummary(**{**defaults, **kwargs})


@pytest.fixture
def insight_repo() -> FakeInsightRepository:
    return FakeInsightRepository()


@pytest.fixture
def llm_generator() -> FakeLLMInsightGenerator:
    return FakeLLMInsightGenerator(
        summary="Good savings rate.", tips=["Cut dining.", "Invest surplus."]
    )


@pytest.fixture
def use_case(
    insight_repo: FakeInsightRepository, llm_generator: FakeLLMInsightGenerator
) -> GenerateInsights:
    return GenerateInsights(insight_repo=insight_repo, llm_generator=llm_generator)


async def test_generate_returns_budget_insight(use_case: GenerateInsights) -> None:
    result = await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert result.year == 2024 and result.month == 1


async def test_generate_insight_belongs_to_user(use_case: GenerateInsights) -> None:
    result = await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert result.user_id == USER_ID


async def test_generate_persists_insight(
    use_case: GenerateInsights, insight_repo: FakeInsightRepository
) -> None:
    await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    saved = await insight_repo.get_by_user_and_month(USER_ID, 2024, 1)
    assert saved is not None


async def test_generate_stores_llm_summary(use_case: GenerateInsights) -> None:
    result = await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert result.llm_summary == "Good savings rate."


async def test_generate_stores_llm_tips(use_case: GenerateInsights) -> None:
    result = await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert "Cut dining." in result.llm_tips


async def test_generate_calculates_savings_rate(use_case: GenerateInsights) -> None:
    result = await use_case.execute(
        GenerateInsightsRequest(
            summary=_make_summary(
                total_income=Decimal("4000"),
                total_expenses=Decimal("2000"),
                net_savings=Decimal("2000"),
            )
        )
    )
    assert result.savings_rate == Decimal("50.00")


async def test_generate_calls_llm_once(
    use_case: GenerateInsights, llm_generator: FakeLLMInsightGenerator
) -> None:
    await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert llm_generator.call_count == 1


async def test_generate_overwrites_existing_insight_for_same_user_and_month(
    use_case: GenerateInsights, insight_repo: FakeInsightRepository
) -> None:
    await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    await use_case.execute(GenerateInsightsRequest(summary=_make_summary()))
    assert len(await insight_repo.list_by_user(USER_ID)) == 1
