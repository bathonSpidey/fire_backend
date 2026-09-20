import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction, DBMonthlyStat
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from services import linking
from services.month_metrics import calculate_metrics
from services.statement_store import save_statement

D = datetime.date


def line(day, amount, who, kind, category=None, month=4):
    return StatementLine(
        booking_date=D(2026, month, day), amount=amount, counterparty=who,
        description=f"{who} {day}.{month}", kind=kind, category=category,
    )


def sparkasse():
    txs = [
        line(24, 3000.0, "Employer", TxKind.INCOME, "SALARY"),
        line(10, -400.0, "Kaufland", TxKind.SPEND, "GROCERIES"),
        line(1, -40.0, "Gym", TxKind.SPEND, "FIXED_COSTS"),
        line(2, -10.0, "Sparkasse", TxKind.FEE),
        line(22, 100.0, "Finanzamt", TxKind.REFUND, "RETURNS"),
        line(24, -300.0, "Abir Bhattacharyya", TxKind.INTERNAL_TRANSFER),
        line(24, -120.0, "Abir Bhattacharyya fonds", TxKind.INVESTMENT),
        line(25, -50.0, "ATM", TxKind.CASH),
    ]
    return StatementSubmission(
        bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=1000.0, closing_balance=1000.0 + sum(t.amount for t in txs), transactions=txs,
    )


def n26(with_transfer=True):
    txs = [line(7, -10.0, "N26 Equities", TxKind.INVESTMENT), line(9, -25.0, "N26 Equities", TxKind.INVESTMENT),
           line(28, 0.19, "N26", TxKind.INCOME, "OTHER_INCOME")]
    if with_transfer:
        txs.append(line(24, 300.0, "Abir Bhattacharyya", TxKind.INTERNAL_TRANSFER))
    return StatementSubmission(
        bank=Bank.N26, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=sum(t.amount for t in txs), transactions=txs,
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def april(db):
    return db.query(DBBankStatement).filter_by(month="Apr", year=2026).all()


def test_transfers_and_investments_are_neither_income_nor_expense(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    m = calculate_metrics(db, april(db), "Apr", 2026)
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
    m = calculate_metrics(db, april(db), "Apr", 2026)
    assert set(m["categories"]) == {
        "SALARY", "RETURNS", "OTHER_INCOME", "GROCERIES", "FIXED_COSTS", "CASH", "INVESTMENT_ORDER",
    }
    assert m["categories"]["INVESTMENT_ORDER"]["total"] == 155.0
    assert m["categories"]["FIXED_COSTS"]["total"] == 50.0  # gym + bank fee
    assert m["categories"]["RETURNS"]["percentage_of_total"] == pytest.approx(3.23, abs=0.01)


def test_unpaired_transfer_is_still_not_counted_as_spending(db):
    # N26 not uploaded yet: the 300 leaving Sparkasse must not look like an expense.
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    m = calculate_metrics(db, april(db), "Apr", 2026)
    assert m["lifestyle_expenses"] == 500.0 and m["total_invested"] == 120.0


def test_a_statement_from_the_retired_parser_gets_a_clear_upload_again_message(db):
    db.add(DBBankStatement(
        bank="Sparkasse", month="May", year=2026, starting_balance=0.0, closing_balance=0.0,
        transactions=[{"date": "04.05.2026", "description": "Lohn, Gehalt", "amount": 1000.0}],
    ))
    db.commit()
    with pytest.raises(HTTPException) as err:
        calculate_metrics(db, db.query(DBBankStatement).all(), "May", 2026)
    assert err.value.status_code == 409 and "Sparkasse May 2026" in err.value.detail
    assert "Upload that statement again" in err.value.detail


def test_changing_a_statement_drops_the_cached_month(db):
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sparkasse())
    db.add(DBMonthlyStat(month="Apr", year=2026, gross_income=1.0, lifestyle_expenses=1.0, net_savings=0.0,
                         total_invested=0.0, savings_rate_pct=0.0, fixed_vs_variable_ratio="0%", categories={}))
    db.add(DBMonthlyStat(month="May", year=2026, gross_income=1.0, lifestyle_expenses=1.0, net_savings=0.0,
                         total_invested=0.0, savings_rate_pct=0.0, fixed_vs_variable_ratio="0%", categories={}))
    db.commit()
    save_statement(db, owner="Abir", source_path="b", file_hash="b", sub=n26())
    assert db.query(DBMonthlyStat).filter_by(month="Apr").count() == 0  # April changed
    assert db.query(DBMonthlyStat).filter_by(month="May").count() == 1  # other months untouched


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
    sub_a = sparkasse()
    save_statement(db, owner="Abir", source_path="a", file_hash="a", sub=sub_a)
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
