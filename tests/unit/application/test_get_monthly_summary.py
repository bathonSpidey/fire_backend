from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from src.fire.application.use_cases.get_monthly_summary import (
    GetMonthlySummary,
    GetMonthlySummaryRequest,
)
from src.fire.domain.entities.transaction import Transaction, TransactionCategory, TransactionType

from tests.fakes import FakeTransactionRepository


def _make_transaction(
    amount: Decimal,
    tx_type: TransactionType,
    category: TransactionCategory,
    tx_date: date,
) -> Transaction:
    return Transaction.create(
        document_id=uuid4(),
        date=tx_date,
        description="test",
        amount=amount,
        transaction_type=tx_type,
        category=category,
    )


@pytest.fixture
def tx_repo() -> FakeTransactionRepository:
    return FakeTransactionRepository()


@pytest.fixture
def use_case(tx_repo: FakeTransactionRepository) -> GetMonthlySummary:
    return GetMonthlySummary(transaction_repo=tx_repo)


async def test_summary_totals_income_correctly(
    use_case: GetMonthlySummary,
    tx_repo: FakeTransactionRepository,
) -> None:
    await tx_repo.save(
        _make_transaction(
            Decimal("3000"), TransactionType.CREDIT, TransactionCategory.INCOME, date(2024, 1, 1)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("500"), TransactionType.CREDIT, TransactionCategory.INCOME, date(2024, 1, 15)
        )
    )
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=1))
    assert result.total_income == Decimal("3500")


async def test_summary_totals_expenses_correctly(
    use_case: GetMonthlySummary,
    tx_repo: FakeTransactionRepository,
) -> None:
    await tx_repo.save(
        _make_transaction(
            Decimal("200"), TransactionType.DEBIT, TransactionCategory.GROCERIES, date(2024, 1, 5)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("50"), TransactionType.DEBIT, TransactionCategory.DINING, date(2024, 1, 10)
        )
    )
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=1))
    assert result.total_expenses == Decimal("250")


async def test_summary_groups_by_category(
    use_case: GetMonthlySummary,
    tx_repo: FakeTransactionRepository,
) -> None:
    await tx_repo.save(
        _make_transaction(
            Decimal("100"), TransactionType.DEBIT, TransactionCategory.GROCERIES, date(2024, 1, 1)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("50"), TransactionType.DEBIT, TransactionCategory.GROCERIES, date(2024, 1, 2)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("80"), TransactionType.DEBIT, TransactionCategory.DINING, date(2024, 1, 3)
        )
    )
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=1))
    assert result.category_totals[TransactionCategory.GROCERIES] == Decimal("150")
    assert result.category_totals[TransactionCategory.DINING] == Decimal("80")


async def test_summary_excludes_other_months(
    use_case: GetMonthlySummary,
    tx_repo: FakeTransactionRepository,
) -> None:
    await tx_repo.save(
        _make_transaction(
            Decimal("100"), TransactionType.DEBIT, TransactionCategory.GROCERIES, date(2024, 1, 1)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("999"), TransactionType.DEBIT, TransactionCategory.GROCERIES, date(2024, 2, 1)
        )
    )
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=1))
    assert result.total_expenses == Decimal("100")


async def test_summary_returns_zero_totals_for_empty_month(
    use_case: GetMonthlySummary,
) -> None:
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=6))
    assert result.total_income == Decimal("0")
    assert result.total_expenses == Decimal("0")
    assert result.transaction_count == 0


async def test_summary_calculates_net_savings(
    use_case: GetMonthlySummary,
    tx_repo: FakeTransactionRepository,
) -> None:
    await tx_repo.save(
        _make_transaction(
            Decimal("3000"), TransactionType.CREDIT, TransactionCategory.INCOME, date(2024, 1, 1)
        )
    )
    await tx_repo.save(
        _make_transaction(
            Decimal("1200"), TransactionType.DEBIT, TransactionCategory.HOUSING, date(2024, 1, 5)
        )
    )
    result = await use_case.execute(GetMonthlySummaryRequest(year=2024, month=1))
    assert result.net_savings == Decimal("1800")
