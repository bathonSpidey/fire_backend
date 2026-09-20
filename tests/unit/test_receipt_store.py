import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBInventoryItem, DBReceipt
from models.inventory import ReceiptLine, ReceiptSubmission, StorageCondition
from services.categories import category_map, seed_categories
from services.receipt_store import find_problems, save_receipt

TODAY = datetime.date(2026, 5, 1)


def line(name, unit_price, qty=1, discount=0.0, category="groceries"):
    return ReceiptLine(
        name=name,
        quantity=qty,
        unit_price=unit_price,
        discount=discount,
        spend_category=category,
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
            line("Pfandartikel", 0.25, qty=3, category="deposit"),  # 0.75
            line("Zitronen 500g", 1.69),  # 1.69 -> total 10.24
        ],
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
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
    sub.items.append(line("Pfandrückgabe", -0.25, category="deposit"))
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


def test_unknown_category_is_rejected_with_the_valid_keys(db):
    sub = kaufland_like()
    sub.items[0].spend_category = "food"  # not a key in the list
    outcome = save_receipt(db, owner="Abir", source_path="x", file_hash="h", sub=sub)
    assert not outcome.ok
    assert "unknown category 'food'" in outcome.message and "groceries" in outcome.message
    assert db.query(DBReceipt).count() == 0


def test_income_category_cannot_be_used_on_a_purchase(db):
    sub = kaufland_like()
    sub.items[0].spend_category = "salary"
    problems = find_problems(sub, today=TODAY, categories=category_map(db))
    assert any("income category" in p for p in problems)


def test_one_receipt_can_hold_several_categories_and_derives_the_pantry_category(db):
    sub = kaufland_like()
    sub.items[1].spend_category = "personal_care"
    sub.items[4].spend_category = "furniture_decor"
    outcome = save_receipt(db, owner="Abir", source_path="x", file_hash="h", sub=sub)
    assert outcome.ok
    rows = {i.name: (i.spend_category, i.category) for i in db.query(DBInventoryItem)}
    assert rows["KFav.Röschentrilo"] == ("personal_care", "Cosmetics")
    assert rows["Zitronen 500g"] == ("furniture_decor", "Living")
    assert rows["Hühner Frikassee"] == ("groceries", "Food")


def test_a_custom_category_is_accepted_once_it_exists(db):
    from services.categories import create_category

    create_category(db, label="Cat food", group_name="Shopping", description="Food for the cat")
    sub = kaufland_like()
    sub.items[0].spend_category = "cat_food"
    assert save_receipt(db, owner="Abir", source_path="x", file_hash="h", sub=sub).ok
    assert db.query(DBInventoryItem).filter_by(spend_category="cat_food").one().category == "Other"


def test_a_review_note_flags_the_receipt_even_when_every_check_passes(db):
    # e.g. a cropped screenshot with no visible date: Claude assumes today and says so
    outcome = save_receipt(
        db, owner="Abir", source_path="x", file_hash="h", sub=kaufland_like(total=10.24),
        review_note="date not visible, assumed the upload day",
    )
    assert outcome.ok
    receipt = db.get(DBReceipt, outcome.receipt_id)
    assert receipt.status == "needs_review"
    assert receipt.review_note == "date not visible, assumed the upload day"


def test_opened_shelf_life_and_starting_quantity_are_stored_for_the_stock(db):
    sub = kaufland_like(total=10.24)
    sub.items[2].days_once_opened = 3  # Müllermilch x3
    outcome = save_receipt(db, owner="Abir", source_path="x", file_hash="h", sub=sub)
    assert outcome.ok
    milk = db.query(DBInventoryItem).filter_by(name="Müllermilch").one()
    assert (milk.days_once_opened, milk.quantity, milk.quantity_left) == (3, 3, 3)
    assert db.query(DBInventoryItem).filter_by(name="Zitronen 500g").one().days_once_opened is None
