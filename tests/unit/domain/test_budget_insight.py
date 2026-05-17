from decimal import Decimal
from uuid import uuid4

from src.fire.domain.entities.budget_insight import BudgetInsight, SpendingBreakdown

USER_ID = uuid4()


def _make_insight(**kwargs) -> BudgetInsight:
    defaults = dict(
        user_id=USER_ID,
        year=2024,
        month=1,
        total_income=Decimal("3000.00"),
        total_expenses=Decimal("1800.00"),
        spending_breakdown=[SpendingBreakdown("groceries", Decimal("400"), 12, Decimal("22.22"))],
        llm_summary="Good month overall.",
        llm_tips=["Cook at home.", "Review subscriptions."],
    )
    return BudgetInsight.create(**{**defaults, **kwargs})


def test_insight_belongs_to_user() -> None:
    assert _make_insight().user_id == USER_ID


def test_insight_calculates_net_savings() -> None:
    assert _make_insight().net_savings == Decimal("1200.00")


def test_insight_calculates_savings_rate() -> None:
    assert _make_insight(
        total_income=Decimal("3000"), total_expenses=Decimal("1500")
    ).savings_rate == Decimal("50.00")


def test_savings_rate_is_zero_when_no_income() -> None:
    assert _make_insight(
        total_income=Decimal("0"), total_expenses=Decimal("500")
    ).savings_rate == Decimal("0")


def test_insight_savings_rate_rounds_to_two_decimals() -> None:
    assert _make_insight(
        total_income=Decimal("3000"), total_expenses=Decimal("2000")
    ).savings_rate == Decimal("33.33")


def test_insight_stores_llm_tips() -> None:
    tips = ["Tip one.", "Tip two."]
    assert _make_insight(llm_tips=tips).llm_tips == tips


def test_insight_fire_progress_note_defaults_to_none() -> None:
    assert _make_insight().fire_progress_note is None


def test_insight_fire_progress_note_can_be_set() -> None:
    assert (
        _make_insight(fire_progress_note="On track for FIRE by 2035!").fire_progress_note
        == "On track for FIRE by 2035!"
    )
