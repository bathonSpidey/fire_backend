import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankTransaction, DBInventoryItem, DBReceipt
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from services import linking
from services.categories import delete_category, seed_categories
from services.spending import month_spending
from services.statement_store import save_statement

D = datetime.date


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def receipt(db, store, day, items, owner="Abir", month=4, total=None, discount=0.0):
    """items: list of (name, category_key, amount)."""
    r = DBReceipt(
        store_name=store, purchase_date=D(2026, month, day), owner=owner, status="ok",
        total_amount=total if total is not None else sum(a for _, _, a in items), total_discount=discount,
    )
    db.add(r)
    db.flush()
    for name, key, amount in items:
        db.add(DBInventoryItem(
            receipt_id=r.id, name=name, quantity=1, unit_cost=amount, discount=0.0, category="Food",
            storage_condition="Normal", date_purchased=r.purchase_date, spend_category=key,
        ))
    db.commit()
    return r


def april_statement(db):
    def line(day, amount, who, kind, category=None, purchase=None):
        return StatementLine(booking_date=D(2026, 4, day), purchase_date=purchase, amount=amount,
                             counterparty=who, description=f"{who} {day}", kind=kind, category=category)
    txs = [
        line(1, -800.0, "Landlord", TxKind.SPEND, "rent"),
        line(14, -109.0, "Kaufland", TxKind.SPEND, "groceries", purchase=D(2026, 4, 10)),
        line(20, -50.0, "Kaufland", TxKind.SPEND, "groceries"),
        line(21, -60.0, "star Tankstelle", TxKind.SPEND, "fuel"),
        line(24, -300.0, "Own account", TxKind.INTERNAL_TRANSFER),
        line(25, -100.0, "Broker", TxKind.INVESTMENT),
        line(24, 3000.0, "Employer", TxKind.INCOME, "salary"),
    ]
    sub = StatementSubmission(bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
                              opening_balance=0.0, closing_balance=sum(t.amount for t in txs), transactions=txs)
    assert save_statement(db, owner="Abir", source_path="s", file_hash="s", sub=sub).ok


def by_key(result):
    return {c["key"]: c for c in result["categories"]}


def test_month_can_be_tracked_from_receipts_alone(db):
    # September situation: receipts only, the statement arrives a month later.
    receipt(db, "Kaufland", 3, [("Milk", "groceries", 60.0), ("Shampoo", "personal_care", 30.0),
                                ("Candle", "furniture_decor", 19.0)])
    result = month_spending(db, 2026, 4)
    assert result["total"] == 109.0 and result["receipt_total"] == 109.0 and result["bank_only_total"] == 0.0
    cats = by_key(result)
    assert (cats["groceries"]["amount"], cats["personal_care"]["amount"], cats["furniture_decor"]["amount"]) == (60.0, 30.0, 19.0)
    assert {g["group"] for g in result["groups"]} == {"Food", "Health & body", "Home"}
    assert result["discrepancies"]["awaiting_statement"] is True
    assert result["discrepancies"]["unmatched_receipts"] == []  # not a problem before the statement


def test_a_linked_bank_booking_is_not_counted_twice(db):
    r = receipt(db, "Kaufland", 10, [("Food", "groceries", 60.0), ("Care", "personal_care", 30.0), ("Home", "household_supplies", 19.0)])
    april_statement(db)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    assert linking.link_receipt(db, tx.id, r.id, "certain", "ref").ok
    result = month_spending(db, 2026, 4)
    # 109 (the receipt's items) + 800 rent + 50 unreceipted Kaufland + 60 fuel. Not 109 twice.
    assert result["total"] == 1019.0
    assert result["receipt_total"] == 109.0 and result["bank_only_total"] == 910.0
    cats = by_key(result)
    assert cats["groceries"]["amount"] == 110.0  # 60 from the receipt + 50 from the bank
    assert cats["groceries"]["receipt_amount"] == 60.0 and cats["groceries"]["bank_amount"] == 50.0
    assert cats["rent"]["amount"] == 800.0 and cats["fuel"]["amount"] == 60.0


def test_transfers_investments_and_income_are_not_spending(db):
    april_statement(db)
    result = month_spending(db, 2026, 4)
    # rent 800 + Kaufland 109 + Kaufland 50 + fuel 60; the 300 transfer, 100 investment and 3000 salary are excluded
    assert result["total"] == 1019.0
    assert set(by_key(result)) == {"rent", "groceries", "fuel"}


def test_bank_purchase_date_decides_the_month_not_the_booking_date(db):
    april_statement(db)  # Kaufland -109 booked 14.04 but bought 10.04
    assert month_spending(db, 2026, 3)["total"] == 0.0
    assert by_key(month_spending(db, 2026, 4))["groceries"]["bank_amount"] == 159.0


def test_discrepancies_show_missing_and_unmatched_receipts(db):
    linked = receipt(db, "Kaufland", 10, [("Food", "groceries", 109.0)])
    receipt(db, "Aldi", 12, [("Food", "groceries", 20.0)])  # never appears on the statement
    april_statement(db)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, linked.id, "certain", "x")
    d = month_spending(db, 2026, 4)["discrepancies"]
    assert d["has_statement"] and not d["awaiting_statement"]
    assert [u["store"] for u in d["unmatched_receipts"]] == ["Aldi"]
    # The unreceipted 50 EUR Kaufland payment is flagged; rent and fuel (no receipts expected) are not.
    assert [(m["counterparty"], m["amount"]) for m in d["missing_receipts"]] == [("Kaufland", 50.0)]


def test_unknown_or_deleted_categories_land_in_uncategorized(db):
    receipt(db, "Shop", 5, [("Thing", "pets", 12.0), ("Other thing", None, 8.0)])
    delete_category(db, "pets")
    result = month_spending(db, 2026, 4)
    assert result["uncategorized"] == {"entries": 2, "amount": 20.0}
    assert by_key(result)["uncategorized"]["label"] == "Uncategorized"


def test_previous_month_and_owner_and_store_breakdowns(db):
    receipt(db, "Kaufland", 3, [("Food", "groceries", 40.0)], owner="Abir", month=3)
    receipt(db, "Kaufland", 3, [("Food", "groceries", 50.0)], owner="Abir")
    receipt(db, "dm", 4, [("Soap", "personal_care", 10.0)], owner="Lena")
    result = month_spending(db, 2026, 4)
    assert result["previous_total"] == 40.0
    assert by_key(result)["groceries"]["previous_amount"] == 40.0
    assert {o["owner"]: o["amount"] for o in result["owners"]} == {"Abir": 50.0, "Lena": 10.0}
    assert result["stores"][0] == {"store": "Kaufland", "amount": 50.0}
    assert result["receipts"]["count"] == 2 and result["receipts"]["average_basket"] == 30.0


def test_january_looks_back_to_december_of_the_previous_year(db):
    receipt(db, "Kaufland", 20, [("Food", "groceries", 33.0)], month=12).purchase_date  # 2026-12
    r = db.query(DBReceipt).one()
    r.purchase_date = D(2025, 12, 20)
    db.commit()
    assert month_spending(db, 2026, 1)["previous_total"] == 33.0
