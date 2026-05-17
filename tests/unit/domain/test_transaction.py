from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from src.fire.domain.entities.transaction import Transaction, TransactionCategory, TransactionType

USER_ID = uuid4()


def _make_debit(**kwargs) -> Transaction:
    defaults = dict(
        user_id=USER_ID,
        document_id=uuid4(),
        date=date(2024, 1, 15),
        description="Supermarket",
        amount=Decimal("42.50"),
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.GROCERIES,
    )
    return Transaction.create(**{**defaults, **kwargs})


def test_transaction_create_assigns_uuid() -> None:
    assert _make_debit().id is not None


def test_transaction_belongs_to_user() -> None:
    assert _make_debit().user_id == USER_ID


def test_transaction_create_stores_fields() -> None:
    doc_id = uuid4()
    t = _make_debit(document_id=doc_id, description="Lidl", amount=Decimal("19.99"))
    assert t.document_id == doc_id and t.description == "Lidl" and t.amount == Decimal("19.99")


def test_transaction_create_raises_on_negative_amount() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _make_debit(amount=Decimal("-10.00"))


def test_signed_amount_is_negative_for_debit() -> None:
    assert _make_debit(amount=Decimal("100.00")).signed_amount == Decimal("-100.00")


def test_signed_amount_is_positive_for_credit() -> None:
    t = Transaction.create(
        user_id=USER_ID,
        document_id=uuid4(),
        date=date(2024, 1, 1),
        description="Salary",
        amount=Decimal("3000.00"),
        transaction_type=TransactionType.CREDIT,
        category=TransactionCategory.INCOME,
    )
    assert t.signed_amount == Decimal("3000.00")


def test_transaction_category_defaults_to_other() -> None:
    t = Transaction.create(
        user_id=USER_ID,
        document_id=uuid4(),
        date=date(2024, 1, 1),
        description="Unknown",
        amount=Decimal("5.00"),
        transaction_type=TransactionType.DEBIT,
    )
    assert t.category == TransactionCategory.OTHER


def test_transaction_merchant_is_optional() -> None:
    assert _make_debit().merchant is None


def test_transaction_not_recurring_by_default() -> None:
    assert _make_debit().is_recurring is False
