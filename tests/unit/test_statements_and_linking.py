import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction, DBReceipt, DBReviewQuestion
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from services import linking
from services.statement_store import find_problems, save_statement, statement_month

D = datetime.date


def line(day, amount, who="Kaufland", kind=TxKind.SPEND, month=4, purchase=None, desc=None):
    return StatementLine(
        booking_date=D(2026, month, day),
        purchase_date=purchase,
        amount=amount,
        counterparty=who,
        description=desc or f"{who} payment {day}.{month}",
        kind=kind,
    )


def april(opening=1000.0, closing=790.0, txs=None, bank=Bank.SPARKASSE):
    return StatementSubmission(
        bank=bank,
        period_start=D(2026, 4, 1),
        period_end=D(2026, 4, 30),
        opening_balance=opening,
        closing_balance=closing,
        transactions=txs
        or [
            line(8, -27.07, purchase=D(2026, 4, 2)),
            line(14, -109.0, purchase=D(2026, 4, 10)),
            line(20, -73.93, who="Netflix"),
        ],
    )


def receipt(db, total, store="Kaufland", day=10, month=4):
    r = DBReceipt(
        store_name=store, total_amount=total, purchase_date=D(2026, month, day),
        owner="Lena", status="ok",
    )
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def save(db, sub, file_hash="h1", owner="Abir", review_note=None):
    return save_statement(
        db, owner=owner, source_path="s.pdf", file_hash=file_hash, sub=sub, review_note=review_note
    )


# ── statement validation ───────────────────────────────────────────────────────────────────
def test_balanced_statement_has_no_problems():
    assert find_problems(april()) == []


def test_balance_mismatch_is_reported():
    problems = find_problems(april(closing=800.0))
    assert len(problems) == 1 and "closing - opening" in problems[0]


def test_bookings_spanning_two_months_are_rejected():
    sub = april(txs=[line(2, -10.0, month=3), line(20, -10.0, month=5)], closing=980.0)
    assert any("span" in p for p in find_problems(sub))


def test_month_comes_from_where_bookings_fall_not_from_a_header():
    sub = april(txs=[line(30, -5.0, month=3), line(2, -5.0), line(9, -5.0)], closing=985.0)
    assert statement_month(sub) == (2026, 4)


# ── saving ────────────────────────────────────────────────────────────────────────────────
def test_save_stores_rows_and_legacy_json(db):
    out = save(db, april())
    assert out.ok and out.month_label == "Apr 2026"
    st = db.get(DBBankStatement, out.statement_id)
    assert (st.month, st.year, st.owner, st.status) == ("Apr", 2026, "Abir", "ok")
    assert db.query(DBBankTransaction).count() == 3
    assert st.transactions[1]["amount"] == -109.0
    assert st.transactions[1]["date"] == "14.04.2026"
    assert st.transactions[1]["description"].startswith("Kaufland:")


def test_unbalanced_statement_is_not_saved_without_review_note(db):
    out = save(db, april(closing=5.0))
    assert not out.ok and "NOT SAVED" in out.message
    assert db.query(DBBankStatement).count() == 0


def test_unbalanced_statement_with_review_note_is_flagged(db):
    out = save(db, april(closing=5.0), review_note="page 3 unreadable")
    assert out.ok
    assert db.get(DBBankStatement, out.statement_id).status == "needs_review"


def test_same_file_is_a_duplicate(db):
    save(db, april())
    assert save(db, april()).duplicate


def test_balance_chain_break_is_a_warning_not_an_error(db):
    save(db, april())
    may = StatementSubmission(
        bank=Bank.SPARKASSE, period_start=D(2026, 5, 1), period_end=D(2026, 5, 31),
        opening_balance=999.0, closing_balance=989.0,
        transactions=[line(4, -10.0, month=5)],
    )
    out = save(db, may, file_hash="h2")
    assert out.ok and any("differs from the closing balance" in w for w in out.warnings)
    assert db.get(DBBankStatement, out.statement_id).status == "needs_review"


def test_reimport_replaces_statement_but_keeps_links_and_answers(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    assert linking.link_receipt(db, tx.id, r.id, "certain", "ref match").ok
    other = db.query(DBBankTransaction).filter_by(amount=-27.07).one()
    r2 = receipt(db, 27.07, day=2)
    linking.link_receipt(db, other.id, r2.id, "likely", "unsure")
    q = db.query(DBReviewQuestion).one()
    linking.answer_question(db, q.id, yes=False)

    again = save(db, april(), file_hash="h-corrected")
    assert again.ok and not again.duplicate
    assert db.query(DBBankStatement).count() == 1
    assert db.query(DBBankTransaction).count() == 3
    kept = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    assert kept.receipt_id == r.id
    assert db.query(DBReviewQuestion).one().status == "no"


def test_reimport_that_drops_a_linked_booking_unlinks_the_receipt(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, r.id, "certain", "x")
    smaller = april(txs=[line(8, -27.07), line(20, -73.93, who="Netflix")], closing=899.0)
    save(db, smaller, file_hash="h3")
    assert db.get(DBReceipt, r.id).bank_statement_linked is False


# ── linking ───────────────────────────────────────────────────────────────────────────────
def test_certain_link_marks_both_sides_and_updates_legacy_json(db):
    out = save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    res = linking.link_receipt(db, tx.id, r.id, "certain", "same amount, Bluecode ref")
    assert res.ok and "LINKED" in res.message
    assert db.get(DBReceipt, r.id).bank_statement_linked is True
    assert db.get(DBBankStatement, out.statement_id).transactions[1]["inventory_purchase_id"] == r.id


def test_link_with_different_amounts_is_rejected(db):
    save(db, april())
    r = receipt(db, 108.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    res = linking.link_receipt(db, tx.id, r.id, "certain", "guess")
    assert not res.ok and "amounts differ" in res.message
    assert db.get(DBReceipt, r.id).bank_statement_linked is False


def test_cannot_link_twice(db):
    save(db, april())
    r1, r2 = receipt(db, 109.0), receipt(db, 109.0, day=11)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    assert linking.link_receipt(db, tx.id, r1.id, "certain", "x").ok
    assert "already linked" in linking.link_receipt(db, tx.id, r2.id, "certain", "x").message


def test_likely_link_becomes_a_question_and_yes_links_it(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    res = linking.link_receipt(db, tx.id, r.id, "likely", "no reference on the receipt")
    assert "QUESTION" in res.message
    assert db.get(DBReceipt, r.id).bank_statement_linked is False
    (q,) = linking.open_questions(db)
    assert "109.00 EUR" in q["question"] and "Kaufland" in q["question"]
    assert linking.answer_question(db, q["id"], yes=True).ok
    db.refresh(tx)
    assert (tx.receipt_id, tx.link_status) == (r.id, "confirmed")
    assert linking.open_questions(db) == []


def test_no_answer_is_final_for_that_pair(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, r.id, "likely", "unsure")
    (q,) = linking.open_questions(db)
    linking.answer_question(db, q["id"], yes=False)
    again = linking.link_receipt(db, tx.id, r.id, "likely", "unsure again")
    assert not again.ok and "NO" in again.message
    assert linking.open_questions(db) == []


def test_asking_twice_creates_one_question(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, r.id, "likely", "a")
    linking.link_receipt(db, tx.id, r.id, "likely", "b")
    assert len(linking.open_questions(db)) == 1


def test_certain_link_closes_competing_questions_without_blocking_them(db):
    save(db, april())
    r1, r2 = receipt(db, 109.0), receipt(db, 109.0, day=11)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, r2.id, "likely", "maybe")
    linking.link_receipt(db, tx.id, r1.id, "certain", "ref match")
    assert linking.open_questions(db) == []
    assert db.query(DBReviewQuestion).one().status == "superseded"


def test_find_transactions_matches_on_purchase_date_and_amount(db):
    save(db, april())
    hits = linking.find_transactions(db, D(2026, 4, 9), D(2026, 4, 11), amount=109.0)
    assert [h["amount"] for h in hits] == [-109.0]  # booked 14.04, bought 10.04
    assert linking.find_transactions(db, D(2026, 4, 9), D(2026, 4, 11), amount=5.0) == []


def test_find_receipts_hides_linked_by_default(db):
    save(db, april())
    r = receipt(db, 109.0)
    tx = db.query(DBBankTransaction).filter_by(amount=-109.0).one()
    linking.link_receipt(db, tx.id, r.id, "certain", "x")
    assert linking.find_receipts(db, D(2026, 4, 1), D(2026, 4, 30)) == []
    assert len(linking.find_receipts(db, D(2026, 4, 1), D(2026, 4, 30), only_unlinked=False)) == 1


# ── transfers between own accounts ────────────────────────────────────────────────────────
def two_banks(db):
    save(db, april(txs=[line(3, -500.0, who="N26", kind=TxKind.INTERNAL_TRANSFER)], closing=500.0))
    n26 = StatementSubmission(
        bank=Bank.N26, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
        opening_balance=0.0, closing_balance=500.0,
        transactions=[line(4, 500.0, who="Abir Bhattacharyya", kind=TxKind.INTERNAL_TRANSFER)],
    )
    save(db, n26, file_hash="n26")
    return (
        db.query(DBBankTransaction).filter(DBBankTransaction.amount == -500.0).one(),
        db.query(DBBankTransaction).filter(DBBankTransaction.amount == 500.0).one(),
    )


def test_certain_transfer_pairs_both_sides(db):
    out_tx, in_tx = two_banks(db)
    assert linking.link_transfer(db, out_tx.id, in_tx.id, "certain", "same amount next day").ok
    db.refresh(out_tx); db.refresh(in_tx)
    assert out_tx.transfer_group == in_tx.transfer_group == out_tx.id


def test_transfer_needs_matching_amounts_and_two_accounts(db):
    out_tx, in_tx = two_banks(db)
    in_tx.amount = 499.0
    db.commit()
    assert "amounts differ" in linking.link_transfer(db, out_tx.id, in_tx.id, "certain", "x").message


def test_transfer_on_same_statement_is_rejected(db):
    save(db, april(txs=[line(3, -50.0), line(4, 50.0)], closing=1000.0))
    a = db.query(DBBankTransaction).filter(DBBankTransaction.amount < 0).one()
    b = db.query(DBBankTransaction).filter(DBBankTransaction.amount > 0).one()
    assert "same statement" in linking.link_transfer(db, a.id, b.id, "certain", "x").message


def test_reimport_replaces_a_legacy_statement_that_has_no_owner(db):
    legacy = DBBankStatement(
        bank="Sparkasse", month="Apr", year=2026, starting_balance=1.0, closing_balance=2.0,
        transactions=[{"date": "01.04.2026", "description": "old parser", "amount": 1.0}],
    )
    db.add(legacy)
    db.commit()
    out = save(db, april())
    assert out.ok
    rows = db.query(DBBankStatement).all()
    assert len(rows) == 1 and rows[0].owner == "Abir"


def screenshots(txs=None):
    return StatementSubmission(
        bank=Bank.SPARKASSE, period_start=D(2026, 4, 8), period_end=D(2026, 4, 20),
        opening_balance=None, closing_balance=None,
        transactions=txs or [line(8, -27.07), line(14, -109.0)],
    )


def test_partial_screenshots_are_saved_but_flagged_for_review(db):
    out = save(db, screenshots())
    assert out.ok and not out.duplicate
    st = db.get(DBBankStatement, out.statement_id)
    assert st.status == "needs_review" and "completeness" in st.review_note


def test_partial_screenshots_never_overwrite_a_verified_statement(db):
    full = save(db, april())
    out = save(db, screenshots(), file_hash="shots")
    assert out.ok and out.duplicate and "NOTHING IMPORTED" in out.message
    assert out.statement_id == full.statement_id
    assert db.query(DBBankStatement).count() == 1
    assert db.query(DBBankTransaction).count() == 3  # untouched


def test_a_full_statement_replaces_earlier_screenshots(db):
    save(db, screenshots(), file_hash="shots")
    out = save(db, april(), file_hash="pdf")
    assert out.ok and not out.duplicate
    st = db.query(DBBankStatement).one()
    assert st.status == "ok" and db.query(DBBankTransaction).count() == 3


def test_a_second_partial_set_replaces_the_first_partial_set(db):
    save(db, screenshots(), file_hash="a")
    save(db, screenshots(txs=[line(8, -27.07), line(14, -109.0), line(20, -73.93)]), file_hash="b")
    assert db.query(DBBankStatement).count() == 1
    assert db.query(DBBankTransaction).count() == 3


def test_a_statement_with_only_a_closing_balance_is_still_partial(db):
    # Screenshots often show the closing balance but not the opening one.
    only_closing = screenshots()
    only_closing.closing_balance = 790.0
    save(db, only_closing, file_hash="shots")
    out = save(db, april(), file_hash="pdf")  # the complete statement may replace it
    assert out.ok and not out.duplicate
    assert db.query(DBBankStatement).one().status == "ok"
