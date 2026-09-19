import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBInventoryItem, DBReceipt
from models.inventory import ItemCategory, ReceiptLine, ReceiptSubmission, StorageCondition
from services.receipt_store import find_problems, save_receipt

TODAY = datetime.date(2026, 5, 1)


def line(name, unit_price, qty=1, discount=0.0, category=ItemCategory.FOOD):
    return ReceiptLine(
        name=name,
        quantity=qty,
        unit_price=unit_price,
        discount=discount,
        category=category,
        storage_condition=StorageCondition.NORMAL,
    )


def kaufland_like(total=10.24):
    # Shaped like KauflandApril10.pdf: multi-quantity, a discount line, and Pfand.
    return ReceiptSubmission(
        store_name="Kaufland",
        purchase_date=datetime.date(2026, 4, 10),
        total_amount=total,
        payment_method="Kaufland Pay",
        receipt_number="65148",
        items=[
            line("Hühner Frikassee", 2.22, qty=2),  # 4.44
            line("KFav.Röschentrilo", 1.99, discount=0.40),  # 1.59
            line("Müllermilch", 0.59, qty=3),  # 1.77
            line("Pfandartikel", 0.25, qty=3, category=ItemCategory.DEPOSIT),  # 0.75
            line("Zitronen 500g", 1.69),  # 1.69 -> total 10.24
        ],
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def test_consistent_receipt_has_no_problems():
    sub = kaufland_like(total=10.24)
    assert find_problems(sub, today=TODAY) == []


def test_sum_mismatch_is_reported_with_the_difference():
    problems = find_problems(kaufland_like(total=109.00), today=TODAY)
    assert len(problems) == 1
    assert "Items sum to 10.24" in problems[0]


def test_discount_as_negative_item_is_rejected():
    sub = kaufland_like(total=9.84)
    sub.items.append(line("K Card XTRA Rabatt", -0.40))
    assert any("negative price" in p for p in find_problems(sub, today=TODAY))


def test_deposit_refund_may_be_negative():
    sub = kaufland_like(total=9.99)
    sub.items.append(line("Pfandrückgabe", -0.25, category=ItemCategory.DEPOSIT))
    assert find_problems(sub, today=TODAY) == []


def test_future_date_is_rejected():
    sub = kaufland_like(total=10.24)
    sub.purchase_date = datetime.date(2026, 12, 1)
    assert any("future" in p for p in find_problems(sub, today=TODAY))


def test_save_persists_receipt_items_and_totals(db):
    outcome = save_receipt(
        db, owner="Abir", source_path="x.pdf", file_hash="h1", sub=kaufland_like(total=10.24)
    )
    assert outcome.ok and not outcome.duplicate
    receipt = db.get(DBReceipt, outcome.receipt_id)
    assert (receipt.owner, receipt.status, receipt.total_discount) == ("Abir", "ok", 0.40)
    discounted = db.query(DBInventoryItem).filter_by(name="KFav.Röschentrilo").one()
    assert (discounted.unit_cost, discounted.discount) == (1.99, 0.40)


def test_inconsistent_receipt_is_not_saved_without_review_note(db):
    outcome = save_receipt(
        db, owner="Abir", source_path="x.pdf", file_hash="h1", sub=kaufland_like(total=109.0)
    )
    assert not outcome.ok and "NOT SAVED" in outcome.message
    assert db.query(DBReceipt).count() == 0


def test_inconsistent_receipt_with_review_note_is_flagged(db):
    outcome = save_receipt(
        db,
        owner="Abir",
        source_path="x.pdf",
        file_hash="h1",
        sub=kaufland_like(total=109.0),
        review_note="bottom of the receipt is cut off",
    )
    assert outcome.ok
    receipt = db.get(DBReceipt, outcome.receipt_id)
    assert receipt.status == "needs_review"
    assert "cut off" in receipt.review_note


def test_same_file_or_same_purchase_is_a_duplicate(db):
    first = save_receipt(
        db, owner="Abir", source_path="a.pdf", file_hash="h1", sub=kaufland_like(total=10.24)
    )
    same_file = save_receipt(
        db, owner="Abir", source_path="a.pdf", file_hash="h1", sub=kaufland_like(total=10.24)
    )
    photo_of_same_bon = save_receipt(
        db, owner="Lena", source_path="b.jpg", file_hash="h2", sub=kaufland_like(total=10.24)
    )
    assert same_file.duplicate and photo_of_same_bon.duplicate
    assert same_file.receipt_id == photo_of_same_bon.receipt_id == first.receipt_id
    assert db.query(DBReceipt).count() == 1


def test_same_shop_day_total_but_different_bon_is_a_new_purchase(db):
    save_receipt(
        db, owner="Abir", source_path="a.pdf", file_hash="h1", sub=kaufland_like(total=10.24)
    )
    other = kaufland_like(total=10.24)
    other.receipt_number = "65999"
    outcome = save_receipt(db, owner="Abir", source_path="b.pdf", file_hash="h2", sub=other)
    assert not outcome.duplicate
    assert db.query(DBReceipt).count() == 2
