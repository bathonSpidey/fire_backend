from decimal import Decimal

from src.fire.domain.entities.budget_insight import BudgetInsight, SpendingBreakdown


def _make_insight(**kwargs) -> BudgetInsight:
    defaults = dict(
        year=2024,
        month=1,
        total_income=Decimal("3000.00"),
        total_expenses=Decimal("1800.00"),
        spending_breakdown=[SpendingBreakdown("groceries", Decimal("400"), 12, Decimal("22.22"))],
        llm_summary="Good month overall.",
        llm_tips=["Cook at home more.", "Review subscriptions."],
    )
    return BudgetInsight.create(**{**defaults, **kwargs})


def test_insight_calculates_net_savings():
    insight = _make_insight(
        total_income=Decimal("3000.00"),
        total_expenses=Decimal("1800.00"),
    )
    assert insight.net_savings == Decimal("1200.00")


def test_insight_calculates_savings_rate():
    insight = _make_insight(
        total_income=Decimal("3000.00"),
        total_expenses=Decimal("1500.00"),
    )
    assert insight.savings_rate == Decimal("50.00")


def test_savings_rate_is_zero_when_no_income():
    insight = _make_insight(total_income=Decimal("0"), total_expenses=Decimal("500"))
    assert insight.savings_rate == Decimal("0")


def test_insight_savings_rate_rounds_to_two_decimals():
    insight = _make_insight(
        total_income=Decimal("3000.00"),
        total_expenses=Decimal("2000.00"),
    )
    assert insight.savings_rate == Decimal("33.33")


def test_insight_stores_llm_tips():
    tips = ["Tip one.", "Tip two."]
    insight = _make_insight(llm_tips=tips)
    assert insight.llm_tips == tips


def test_insight_fire_progress_note_defaults_to_none():
    insight = _make_insight()
    assert insight.fire_progress_note is None


def test_insight_fire_progress_note_can_be_set():
    insight = _make_insight(fire_progress_note="On track for FIRE by 2035!")
    assert insight.fire_progress_note == "On track for FIRE by 2035!"
