import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction, DBInventoryItem, DBReceipt
from services.categories import seed_categories
from services.spending_trends import pace, trends

D = datetime.date
TODAY = D(2026, 9, 20)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def receipt(db, date, key, amount, store="Kaufland"):
    r = DBReceipt(store_name=store, purchase_date=date, owner="Abir", status="ok", total_amount=amount)
    db.add(r)
    db.flush()
    db.add(DBInventoryItem(receipt_id=r.id, name="thing", quantity=1, unit_cost=amount, discount=0.0, category="Food",
                           storage_condition="Normal", date_purchased=date, spend_category=key))
    db.commit()


def bank(db, date, amount, who, key):
    st = DBBankStatement(bank="Sparkasse", month="Jan", year=2026, starting_balance=0, closing_balance=0,
                         transactions=[])
    db.add(st)
    db.flush()
    db.add(DBBankTransaction(statement_id=st.id, booking_date=date, amount=-amount, counterparty=who,
                             description=who, kind="spend", category=key))
    db.commit()


def month_of(result, year, month):
    return next(m for m in result["months"] if (m["year"], m["month"]) == (year, month))


def test_months_are_listed_oldest_first_with_empty_ones_kept(db):
    receipt(db, D(2026, 7, 3), "groceries", 50.0)
    result = trends(db, 3, 2026, 9, TODAY)
    assert [(m["year"], m["month"]) for m in result["months"]] == [(2026, 7), (2026, 8), (2026, 9)]
    assert [m["total"] for m in result["months"]] == [50.0, 0, 0]
    assert result["months"][0]["label"] == "Jul 26"


def test_the_current_month_is_partial_and_never_a_baseline(db):
    receipt(db, D(2026, 8, 3), "groceries", 100.0)
    receipt(db, D(2026, 9, 3), "groceries", 900.0)  # big, but the month is not over
    result = trends(db, 3, 2026, 9, TODAY)
    assert month_of(result, 2026, 9)["partial"] and not month_of(result, 2026, 8)["partial"]
    assert result["average_total"] == 100.0
    groceries = next(c for c in result["categories"] if c["key"] == "groceries")
    assert (groceries["total"], groceries["average"]) == (1000.0, 100.0)


def test_fixed_and_flexible_costs_are_split(db):
    bank(db, D(2026, 8, 1), 800.0, "Landlord", "rent")  # fixed
    receipt(db, D(2026, 8, 5), "eating_out", 40.0)  # flexible
    august = month_of(trends(db, 2, 2026, 9, TODAY), 2026, 8)
    assert (august["fixed"], august["flexible"], august["total"]) == (800.0, 40.0, 840.0)


def test_a_bank_payment_with_a_receipt_is_not_counted_twice(db):
    receipt(db, D(2026, 8, 5), "groceries", 60.0)
    r = db.query(DBReceipt).one()
    bank(db, D(2026, 8, 6), 60.0, "Kaufland", "groceries")
    tx = db.query(DBBankTransaction).one()
    tx.receipt_id = r.id
    db.commit()
    assert month_of(trends(db, 2, 2026, 9, TODAY), 2026, 8)["total"] == 60.0


def test_movers_compare_the_last_finished_month_with_the_ones_before(db):
    for month, amount in ((6, 100.0), (7, 100.0), (8, 250.0)):
        receipt(db, D(2026, month, 10), "eating_out", amount)
        receipt(db, D(2026, month, 11), "groceries", 300.0 if month < 8 else 200.0)
    movers = trends(db, 4, 2026, 9, TODAY)["movers"]
    assert movers["month"] == "Aug 26" and movers["baseline_months"] == 2
    assert [m["key"] for m in movers["up"]] == ["eating_out"]
    assert movers["up"][0]["change"] == 150.0 and movers["up"][0]["change_pct"] == 150
    assert [m["key"] for m in movers["down"]] == ["groceries"]


def test_small_changes_are_not_movers(db):
    receipt(db, D(2026, 7, 10), "groceries", 100.0)
    receipt(db, D(2026, 8, 10), "groceries", 105.0)
    movers = trends(db, 3, 2026, 9, TODAY)["movers"]
    assert movers["up"] == [] and movers["down"] == []


def test_movers_need_two_finished_months(db):
    receipt(db, D(2026, 8, 10), "groceries", 100.0)
    assert trends(db, 3, 2026, 9, TODAY)["movers"]["month"] is None


def test_pace_runs_up_by_day_against_the_previous_month(db):
    receipt(db, D(2026, 8, 2), "groceries", 30.0)
    receipt(db, D(2026, 8, 25), "groceries", 20.0)  # after day 20, so not yet part of "the same day"
    receipt(db, D(2026, 9, 2), "groceries", 40.0)
    receipt(db, D(2026, 9, 3), "groceries", 10.0)
    result = pace(db, 2026, 9, TODAY)
    assert len(result["current"]) == 20  # up to today, not the whole month
    assert result["current"][0] == 0 and result["current"][1] == 40.0 and result["current"][2] == 50.0
    assert result["current_total"] == 50.0
    assert (result["previous_same_day"], result["previous_total"]) == (30.0, 50.0)
    assert result["in_progress"]


def test_a_finished_month_shows_all_its_days(db):
    receipt(db, D(2026, 8, 31), "groceries", 10.0)
    result = pace(db, 2026, 8, TODAY)
    assert len(result["current"]) == 31 and result["current_total"] == 10.0 and not result["in_progress"]


def test_a_receipts_only_month_is_flagged_as_unfair_against_a_month_with_the_bank(db):
    bank(db, D(2026, 8, 1), 800.0, "Landlord", "rent")
    receipt(db, D(2026, 9, 2), "groceries", 40.0)
    assert pace(db, 2026, 9, TODAY)["unfair_comparison"]
    bank(db, D(2026, 9, 1), 800.0, "Landlord", "rent")
    assert not pace(db, 2026, 9, TODAY)["unfair_comparison"]
