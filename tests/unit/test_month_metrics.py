import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction, DBInventoryItem, DBReceipt
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from services import linking
from services.categories import delete_category, seed_categories, update_category
from services.month_metrics import calculate_metrics
from services.spending import month_spending
from services.statement_store import save_statement

D = datetime.date


def line(day, amount, who, kind, category=None, month=4):
    return StatementLine(
        booking_date=D(2026, month, day), amount=amount, counterparty=who,
        description=f"{who} {day}.{month}", kind=kind, category=category,
    )


def sparkasse():
    txs = [
        line(24, 3000.0, "Employer", TxKind.INCOME, "salary"),
        line(10, -400.0, "Kaufland", TxKind.SPEND, "groceries"),
        line(1, -40.0, "Gym", TxKind.SPEND, "fitness"),
        line(2, -10.0, "Sparkasse", TxKind.FEE),
        line(22, 100.0, "Finanzamt", TxKind.REFUND, "tax_refund"),
        line(24, -300.0, "Abir Bhattacharyya", TxKind.INTERNAL_TRANSFER),
        line(24, -120.0, "Abir Bhattacharyya fonds", TxKind.INVESTMENT),
        line(25, -50.0, "ATM", TxKind.CASH),
    ]
    return StatementSubmission(
        bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=1000.0, closing_balance=1000.0 + sum(t.amount for t in txs), transactions=txs,
    )


def n26():
    txs = [line(7, -10.0, "N26 Equities", TxKind.INVESTMENT), line(9, -25.0, "N26 Equities", TxKind.INVESTMENT),
           line(28, 0.19, "N26", TxKind.INCOME, "other_income"), line(24, 300.0, "Abir Bhattacharyya", TxKind.INTERNAL_TRANSFER)]
    return StatementSubmission(
        bank=Bank.N26, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=sum(t.amount for t in txs), transactions=txs,
    )


def receipt(db, store, day, items, month=4, owner="Abir"):
    """items: list of (name, category_key, amount)."""
    r = DBReceipt(store_name=store, purchase_date=D(2026, month, day), owner=owner, status="ok",
                  total_amount=sum(a for _, _, a in items), total_discount=0.0)
    db.add(r)
    db.flush()
    for name, key, amount in items:
        db.add(DBInventoryItem(receipt_id=r.id, name=name, quantity=1, unit_cost=amount, discount=0.0, category="Food",
                               storage_condition="Normal", date_purchased=r.purchase_date, spend_category=key))
    db.commit()
    return r


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def april(db):
    return calculate_metrics(db, "Apr", 2026)


# ── bank truth for income and investments, spending by kind ────────────────────────────────
def test_transfers_and_investments_are_neither_income_nor_expense(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    m = april(db)
    # income: salary 3000 + tax refund 100 + N26 interest 0.19. NOT the 300 that arrived on N26.
    assert m["gross_income"] == 3100.19
    # expenses: groceries 400 + gym 40 + fee 10 + cash 50. NOT the 300 transfer or investments.
    assert m["lifestyle_expenses"] == 500.0
    # invested: fund 120 + N26 orders 35. The 300 moved to N26 is not counted a second time.
    assert m["total_invested"] == 155.0
    assert m["net_savings"] == 2600.19


def test_investment_orders_are_never_listed_as_income_categories(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    m = april(db)
    assert set(m["categories"]) == {
        "salary", "tax_refund", "other_income", "groceries", "fitness", "bank_fees", "cash", "investments",
    }
    assert m["categories"]["investments"]["total"] == 155.0
    assert m["categories"]["investments"]["flow"] == "investment"
    assert m["categories"]["salary"]["flow"] == "income"
    assert m["categories"]["groceries"]["label"] == "Groceries"
    assert m["categories"]["tax_refund"]["percentage_of_total"] == pytest.approx(3.23, abs=0.01)
    assert m["fixed_vs_variable_ratio"] == "10% Fixed / 90% Variable"  # gym 40 + bank fee 10 of 500


def test_unpaired_transfer_is_still_not_counted_as_spending(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    m = april(db)
    assert m["lifestyle_expenses"] == 500.0 and m["total_invested"] == 120.0


def test_a_statement_from_the_retired_parser_gets_a_clear_upload_again_message(db):
    db.add(DBBankStatement(
        bank="Sparkasse", month="May", year=2026, starting_balance=0.0, closing_balance=0.0,
        transactions=[{"date": "04.05.2026", "description": "Lohn, Gehalt", "amount": 1000.0}],
    ))
    db.commit()
    with pytest.raises(HTTPException) as err:
        calculate_metrics(db, "May", 2026)
    assert err.value.status_code == 409 and "Sparkasse May 2026" in err.value.detail
    assert "Upload that statement again" in err.value.detail


def test_a_month_with_nothing_recorded_is_none(db):
    assert calculate_metrics(db, "Jun", 2026) is None


def test_a_deleted_category_shows_up_as_uncategorized_not_as_nonsense(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    delete_category(db, "groceries")
    m = april(db)
    assert "groceries" not in m["categories"]
    assert m["categories"]["uncategorized"]["total"] == 400.0
    assert m["categories"]["uncategorized"]["label"] == "Uncategorized"


def test_the_fixed_cost_ratio_follows_the_category_setting(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    update_category(db, "groceries", fixed=True)  # 400 more counted as fixed
    assert april(db)["fixed_vs_variable_ratio"] == "90% Fixed / 10% Variable"


# ── receipts feed the dashboard too (the September situation) ───────────────────────────────
def test_receipts_alone_make_a_month_meaningful_before_any_statement(db):
    receipt(db, "Kaufland", 20, [("Milk", "groceries", 60.0), ("Soap", "personal_care", 37.46)], month=9)
    receipt(db, "Lidl", 3, [("Bars", "groceries", 4.98)], month=9)
    m = calculate_metrics(db, "Sep", 2026)
    assert m["lifestyle_expenses"] == 102.44
    assert m["gross_income"] == 0.0 and m["total_invested"] == 0.0
    assert m["categories"]["groceries"]["total"] == 64.98
    assert m["categories"]["personal_care"]["total"] == 37.46
    assert m["sources"] == {"statements": [], "receipts": 2, "receipt_total": 102.44, "bank_only_total": 0.0}


def test_a_receipt_linked_to_its_bank_booking_is_counted_once(db):
    r = receipt(db, "Kaufland", 10, [("Food", "groceries", 60.0), ("Care", "personal_care", 40.0)])
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    tx = db.query(DBBankTransaction).filter_by(counterparty="Kaufland").one()
    tx.amount = -100.0
    db.commit()
    assert linking.link_receipt(db, tx.id, r.id, "certain", "ref").ok
    m = april(db)
    # gym 40 + fee 10 + cash 50 + the receipt's 100 (split by item). The 100 EUR bank booking is not added again.
    assert m["lifestyle_expenses"] == 200.0
    assert m["categories"]["groceries"]["total"] == 60.0 and m["categories"]["personal_care"]["total"] == 40.0
    assert m["sources"] == {"statements": ["Sparkasse"], "receipts": 1, "receipt_total": 100.0, "bank_only_total": 100.0}


def test_unlinked_receipts_and_bank_only_payments_both_count(db):
    receipt(db, "Aldi", 12, [("Food", "groceries", 20.0)])
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    assert april(db)["lifestyle_expenses"] == 520.0  # the bank's 500 + the receipt not (yet) on the statement


def test_the_dashboard_and_the_spending_page_always_agree_on_spending(db):
    receipt(db, "Aldi", 12, [("Food", "groceries", 20.0)])
    r = receipt(db, "Kaufland", 10, [("Food", "groceries", 400.0)])
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    linking.link_receipt(db, db.query(DBBankTransaction).filter_by(counterparty="Kaufland").one().id, r.id, "certain", "ref")
    assert april(db)["lifestyle_expenses"] == month_spending(db, 2026, 4)["total"]


def test_a_category_change_shows_up_immediately_because_nothing_is_cached(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    assert "groceries" in april(db)["categories"]
    tx = db.query(DBBankTransaction).filter_by(counterparty="Kaufland").one()
    tx.category = "pets"
    db.commit()
    m = april(db)
    assert "groceries" not in m["categories"] and m["categories"]["pets"]["total"] == 400.0


# ── deterministic pairing safety net ────────────────────────────────────────────────────────
def test_auto_pair_links_the_obvious_transfer_and_refreshes_the_cache(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    assert linking.auto_pair_transfers(db) == 1
    out_tx = db.query(DBBankTransaction).filter_by(amount=-300.0).one()
    in_tx = db.query(DBBankTransaction).filter_by(amount=300.0).one()
    assert out_tx.transfer_group == in_tx.transfer_group == out_tx.id
    assert linking.auto_pair_transfers(db) == 0  # nothing left to do


def test_auto_pair_pairs_an_investment_marked_side_too(db):
    # Claude labelled the fund purchase "investment" on one side and "internal_transfer" on the other.
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    commerz = StatementSubmission(
        bank=Bank.COMMERZBANK, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=120.0,
        transactions=[line(25, 120.0, "Abir Bhattacharyya", TxKind.INTERNAL_TRANSFER)],
    )
    save_statement(db, owner="Abir", source_path="c", file_hash="c", sub=commerz)
    assert linking.auto_pair_transfers(db) == 1
    assert db.query(DBBankTransaction).filter_by(amount=-120.0).one().kind == "internal_transfer"


def test_auto_pair_leaves_ambiguous_cases_alone(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=StatementSubmission(
        bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=-600.0,
        transactions=[line(24, -300.0, "Own", TxKind.INTERNAL_TRANSFER), line(25, -300.0, "Own", TxKind.INTERNAL_TRANSFER)],
    ))
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=StatementSubmission(
        bank=Bank.N26, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=300.0,
        transactions=[line(24, 300.0, "Own", TxKind.INTERNAL_TRANSFER)],
    ))
    assert linking.auto_pair_transfers(db) == 0  # two possible sources for one arrival


def test_auto_pair_ignores_amounts_too_far_apart_in_time(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    late = StatementSubmission(
        bank=Bank.N26, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=300.0,
        transactions=[line(30, 300.0, "Own", TxKind.INTERNAL_TRANSFER)],  # 6 days after the 24th
    )
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=late)
    assert linking.auto_pair_transfers(db) == 0
