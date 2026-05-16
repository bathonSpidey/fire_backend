from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from src.fire.domain.entities.transaction import (
    Transaction,
    TransactionCategory,
    TransactionType,
)


def _make_debit(**kwargs) -> Transaction:
    defaults = dict(
        document_id=uuid4(),
        date=date(2024, 1, 15),
        description="Supermarket",
        amount=Decimal("42.50"),
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.GROCERIES,
    )
    return Transaction.create(**{**defaults, **kwargs})


def test_transaction_create_assigns_uuid():
    t = _make_debit()
    assert t.id is not None


def test_transaction_create_stores_fields():
    doc_id = uuid4()
    t = _make_debit(document_id=doc_id, description="Lidl", amount=Decimal("19.99"))
    assert t.document_id == doc_id
    assert t.description == "Lidl"
    assert t.amount == Decimal("19.99")


def test_transaction_create_raises_on_negative_amount():
    with pytest.raises(ValueError, match="non-negative"):
        _make_debit(amount=Decimal("-10.00"))


def test_signed_amount_is_negative_for_debit():
    t = _make_debit(amount=Decimal("100.00"))
    assert t.signed_amount == Decimal("-100.00")


def test_signed_amount_is_positive_for_credit():
    t = Transaction.create(
        document_id=uuid4(),
        date=date(2024, 1, 1),
        description="Salary",
        amount=Decimal("3000.00"),
        transaction_type=TransactionType.CREDIT,
        category=TransactionCategory.INCOME,
    )
    assert t.signed_amount == Decimal("3000.00")


def test_transaction_category_defaults_to_other():
    t = Transaction.create(
        document_id=uuid4(),
        date=date(2024, 1, 1),
        description="Unknown charge",
        amount=Decimal("5.00"),
        transaction_type=TransactionType.DEBIT,
    )
    assert t.category == TransactionCategory.OTHER


def test_transaction_merchant_is_optional():
    t = _make_debit()
    assert t.merchant is None


def test_transaction_not_recurring_by_default():
    t = _make_debit()
    assert t.is_recurring is False
