import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction, DBReviewQuestion
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from services import linking
from services.categories import seed_categories
from services.month_metrics import calculate_metrics
from services.spending import month_spending
from services.statement_store import delete_statement, save_statement

D = datetime.date


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def row(day, amount, who, kind=TxKind.SPEND, category="subscriptions", ref=None, channel=None, text=None, month=4):
    return StatementLine(
        booking_date=D(2026, month, day), amount=amount, counterparty=who,
        description=text or f"{who} {day}", kind=kind, channel=channel, payment_reference=ref,
        category=category if kind in (TxKind.SPEND, TxKind.INCOME, TxKind.REFUND) else None,
    )


def sparkasse(db, txs=None, file_hash="sp"):
    txs = txs or [
        row(2, -4.99, "Netflix", ref="1049307212127", channel="PayPal", category=None,
            text="PayPal Europe 1049307212127 Ihr Einkauf bei Netflix.com"),
        row(8, -2596.04, "Deutsche Lufthansa", ref="1049408825760", channel="PayPal", category=None,
            text="PayPal Europe 1049408825760 Ihr Einkauf bei Deutsche Lufthansa AG"),
        row(1, -800.0, "Landlord", category="rent"),
    ]
    txs = [t.model_copy(update={"category": t.category or "other_expense"}) if t.kind == TxKind.SPEND else t for t in txs]
    sub = StatementSubmission(bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
                              opening_balance=0.0, closing_balance=sum(t.amount for t in txs), transactions=txs)
    out = save_statement(db, owner="Abir", source_path="s", file_hash=file_hash, sub=sub)
    assert out.ok, out.message
    return out


def paypal(db, txs=None, file_hash="pp"):
    txs = txs or [
        row(2, -4.99, "Netflix", ref="1049307212127", channel="PayPal"),
        row(8, -2596.04, "Deutsche Lufthansa", ref="1049408825760", channel="PayPal", category="flights"),
    ]
    sub = StatementSubmission(bank=Bank.PAYPAL, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
                              opening_balance=None, closing_balance=None, transactions=txs)
    out = save_statement(db, owner="Abir", source_path="p", file_hash=file_hash, sub=sub)
    assert out.ok, out.message
    return out


def tx(db, who, bank):
    return (db.query(DBBankTransaction).join(DBBankStatement)
            .filter(DBBankTransaction.counterparty == who, DBBankStatement.bank == bank).one())


# ── PayPal is a list, not a bank ───────────────────────────────────────────────────────────
def test_paypal_lists_are_never_flagged_for_missing_balances(db):
    out = paypal(db)
    st = db.get(DBBankStatement, out.statement_id)
    assert st.status == "ok" and st.review_note is None


def test_a_later_paypal_upload_for_the_same_month_merges_instead_of_replacing(db):
    paypal(db)
    second = paypal(db, file_hash="pp2", txs=[
        row(2, -4.99, "Netflix", ref="1049307212127", channel="PayPal"),  # overlap with the first upload
        row(20, -12.0, "Spotify", channel="PayPal"),
    ])
    assert second.message.startswith("Merged into PayPal statement #1")
    assert "1 new transactions added, 1 already present" in second.message
    assert db.query(DBBankStatement).filter_by(bank="PayPal").count() == 1
    assert sorted(t.counterparty for t in db.query(DBBankTransaction).join(DBBankStatement).filter(DBBankStatement.bank == "PayPal")) == [
        "Deutsche Lufthansa", "Netflix", "Spotify"]


def test_merging_keeps_genuinely_repeated_payments_but_not_overlap_copies(db):
    paypal(db, txs=[row(15, -5.0, "Vodafone", channel="PayPal")])
    # the next screenshot shows the same day twice (a real second payment) plus the first one again
    out = paypal(db, file_hash="pp2", txs=[row(15, -5.0, "Vodafone", channel="PayPal"), row(15, -5.0, "Vodafone", channel="PayPal")])
    assert "1 new transactions added, 1 already present" in out.message
    assert db.query(DBBankTransaction).filter_by(counterparty="Vodafone").count() == 2


def test_merging_widens_the_period_and_never_touches_other_banks(db):
    sparkasse(db)
    paypal(db)
    paypal(db, file_hash="pp2", txs=[row(28, -3.0, "Kiosk", channel="PayPal", category="eating_out")])
    st = db.query(DBBankStatement).filter_by(bank="PayPal").one()
    assert st.period_end == D(2026, 4, 30)
    assert db.query(DBBankStatement).filter_by(bank="Sparkasse").count() == 1


# ── linking a PayPal row to the bank booking it explains ───────────────────────────────────
def test_link_mirror_marks_the_paypal_row_and_enriches_the_opaque_bank_booking(db):
    sparkasse(db)
    paypal(db)
    bank, detail = tx(db, "Deutsche Lufthansa", "Sparkasse"), tx(db, "Deutsche Lufthansa", "PayPal")
    bank.category, bank.counterparty = "other_expense", "PayPal Europe S.a.r.l."
    db.commit()
    res = linking.link_mirror(db, detail.id, bank.id, "certain", "same PayPal transaction number")
    assert res.ok and "LINKED" in res.message
    db.refresh(detail); db.refresh(bank)
    assert detail.mirror_of == bank.id and detail.link_status == "auto"
    assert (bank.category, bank.counterparty) == ("flights", "Deutsche Lufthansa")  # detail flows to the bank row
    entry = next(t for t in db.get(DBBankStatement, detail.statement_id).transactions
                 if t["description"].startswith("Deutsche Lufthansa"))
    assert entry["mirror_of"] == bank.id  # the Statements page data knows it is explained


def test_link_mirror_rejects_what_cannot_be_the_same_payment(db):
    sparkasse(db)
    paypal(db, txs=[row(2, -4.99, "Netflix", channel="PayPal"), row(2, 300.0, "Friend", TxKind.INCOME, "other_income", channel="PayPal")])
    netflix_bank, netflix_pp = tx(db, "Netflix", "Sparkasse"), tx(db, "Netflix", "PayPal")
    friend = tx(db, "Friend", "PayPal")
    lufthansa_bank = tx(db, "Deutsche Lufthansa", "Sparkasse")
    assert "not on a PayPal statement" in linking.link_mirror(db, netflix_bank.id, netflix_pp.id, "certain", "x").message
    assert "also PayPal" in linking.link_mirror(db, netflix_pp.id, friend.id, "certain", "x").message
    assert "amounts differ" in linking.link_mirror(db, netflix_pp.id, lufthansa_bank.id, "certain", "x").message
    assert "money out" in linking.link_mirror(db, friend.id, netflix_bank.id, "certain", "x").message
    assert linking.link_mirror(db, netflix_pp.id, netflix_bank.id, "certain", "x").ok
    assert "already explains" in linking.link_mirror(db, netflix_pp.id, netflix_bank.id, "certain", "x").message


def test_a_bank_booking_can_only_be_explained_once(db):
    sparkasse(db)
    paypal(db, txs=[row(2, -4.99, "Netflix", channel="PayPal"), row(3, -4.99, "Netflix", channel="PayPal")])
    first, second = (db.query(DBBankTransaction).join(DBBankStatement)
                     .filter(DBBankStatement.bank == "PayPal").order_by(DBBankTransaction.booking_date).all())
    bank = tx(db, "Netflix", "Sparkasse")
    assert linking.link_mirror(db, first.id, bank.id, "certain", "x").ok
    assert "already explained" in linking.link_mirror(db, second.id, bank.id, "certain", "x").message


def test_a_paypal_row_more_than_ten_days_from_the_booking_is_not_the_same_payment(db):
    sparkasse(db)
    paypal(db, txs=[row(25, -4.99, "Netflix", channel="PayPal")])
    assert "days apart" in linking.link_mirror(db, tx(db, "Netflix", "PayPal").id, tx(db, "Netflix", "Sparkasse").id, "certain", "x").message


def test_unsure_matches_become_questions_and_yes_links_them(db):
    sparkasse(db)
    paypal(db)
    pp, bank = tx(db, "Netflix", "PayPal"), tx(db, "Netflix", "Sparkasse")
    assert "QUESTION" in linking.link_mirror(db, pp.id, bank.id, "likely", "no transaction number").message
    (q,) = linking.open_questions(db)
    assert q["kind"] == "mirror_match" and "PayPal payment to Netflix" in q["question"]
    assert linking.answer_question(db, q["id"], yes=True).ok
    db.refresh(pp)
    assert pp.mirror_of == bank.id and pp.link_status == "confirmed"


def test_a_no_answer_blocks_the_pair_for_good(db):
    sparkasse(db)
    paypal(db)
    pp, bank = tx(db, "Netflix", "PayPal"), tx(db, "Netflix", "Sparkasse")
    linking.link_mirror(db, pp.id, bank.id, "likely", "unsure")
    (q,) = linking.open_questions(db)
    linking.answer_question(db, q["id"], yes=False)
    assert "NO" in linking.link_mirror(db, pp.id, bank.id, "likely", "again").message
    assert db.query(DBReviewQuestion).filter_by(status="no").count() == 1


# ── never counted twice ─────────────────────────────────────────────────────────────────────
def test_a_mirrored_payment_counts_once_in_both_lenses_and_an_unmirrored_one_still_counts(db):
    sparkasse(db)
    paypal(db)
    before = month_spending(db, 2026, 4)["total"]                     # PayPal rows counted next to the bank rows
    assert before == pytest.approx(4.99 * 2 + 2596.04 * 2 + 800.0)
    assert linking.auto_mirror_paypal(db) == 2
    after = month_spending(db, 2026, 4)
    assert after["total"] == pytest.approx(4.99 + 2596.04 + 800.0)    # each payment once
    m = calculate_metrics(db, "Apr", 2026)
    assert m["lifestyle_expenses"] == pytest.approx(4.99 + 2596.04 + 800.0)


def test_real_time_a_paypal_list_alone_is_tracked_like_receipts(db):
    paypal(db)  # the bank statement arrives a month later
    r = month_spending(db, 2026, 4)
    assert r["total"] == pytest.approx(4.99 + 2596.04)
    assert {c["key"] for c in r["categories"]} == {"subscriptions", "flights"}


# ── the automatic pass ──────────────────────────────────────────────────────────────────────
def test_auto_mirror_matches_on_the_paypal_transaction_number(db):
    sparkasse(db)
    paypal(db)
    assert linking.auto_mirror_paypal(db) == 2
    assert tx(db, "Netflix", "PayPal").mirror_of == tx(db, "Netflix", "Sparkasse").id
    assert linking.auto_mirror_paypal(db) == 0  # nothing left


def test_auto_mirror_works_from_screenshots_without_transaction_numbers(db):
    sparkasse(db, txs=[row(15, -5.0, "Vodafone", category="internet_phone", channel="PayPal", text="PayPal Europe Vodafone GmbH Ihr Einkauf")])
    paypal(db, txs=[row(15, -5.0, "Vodafone", category="internet_phone", channel="PayPal")])
    assert linking.auto_mirror_paypal(db) == 1


def test_auto_mirror_leaves_ambiguous_cases_alone(db):
    # two identical PayPal payments, one bank booking: cannot know which one it is
    sparkasse(db, txs=[row(15, -5.0, "Vodafone", category="internet_phone", channel="PayPal", text="PayPal Europe Vodafone GmbH")])
    paypal(db, txs=[row(15, -5.0, "Vodafone", category="internet_phone", channel="PayPal"),
                    row(16, -5.0, "Vodafone", category="internet_phone", channel="PayPal")])
    assert linking.auto_mirror_paypal(db) == 0


def test_auto_mirror_does_not_pair_different_merchants_with_the_same_amount(db):
    sparkasse(db, txs=[row(15, -5.0, "Kiosk", category="groceries", channel="PayPal", text="PayPal Europe Kiosk")])
    paypal(db, txs=[row(15, -5.0, "Vodafone", category="internet_phone", channel="PayPal")])
    assert linking.auto_mirror_paypal(db) == 0


# ── re-importing or removing statements keeps things consistent ─────────────────────────────
def test_reimporting_the_bank_statement_keeps_the_paypal_links(db):
    sparkasse(db)
    paypal(db)
    linking.auto_mirror_paypal(db)
    assert tx(db, "Netflix", "PayPal").mirror_of is not None
    sparkasse(db, file_hash="sp-corrected")  # same bank + month: replaces the old copy
    assert tx(db, "Netflix", "PayPal").mirror_of == tx(db, "Netflix", "Sparkasse").id
    assert db.query(DBBankTransaction).join(DBBankStatement).filter(DBBankStatement.bank == "PayPal").filter(
        DBBankTransaction.mirror_of.isnot(None)).count() == 2


def test_removing_the_bank_statement_releases_the_paypal_rows(db):
    sparkasse(db)
    paypal(db)
    linking.auto_mirror_paypal(db)
    delete_statement(db, db.query(DBBankStatement).filter_by(bank="Sparkasse").one())
    assert db.query(DBBankTransaction).filter(DBBankTransaction.mirror_of.isnot(None)).count() == 0
    assert month_spending(db, 2026, 4)["total"] == pytest.approx(4.99 + 2596.04)  # PayPal counts alone again


# ── what Claude can search for ──────────────────────────────────────────────────────────────
def test_find_transactions_can_focus_on_paypal_or_skip_it_and_hide_explained_rows(db):
    sparkasse(db)
    paypal(db)
    window = (D(2026, 4, 1), D(2026, 4, 30))
    assert {r["bank"] for r in linking.find_transactions(db, *window, only_unlinked=False, bank="PayPal")} == {"PayPal"}
    assert "PayPal" not in {r["bank"] for r in linking.find_transactions(db, *window, only_unlinked=False, exclude_bank="PayPal")}
    linking.auto_mirror_paypal(db)
    assert {r["amount"] for r in linking.find_transactions(db, *window, only_unlinked=False, unmirrored=True)} == {-800.0}
    everything = linking.find_transactions(db, *window, only_unlinked=False)
    assert sum(1 for r in everything if r["mirrored"]) == 4  # two PayPal rows and the two bookings they explain


def test_a_refund_seen_by_paypal_and_by_the_bank_counts_as_income_once(db):
    sparkasse(db, txs=[
        row(9, 171.04, "Zalando", TxKind.REFUND, "refunds_returns", ref="1049476150527", channel="PayPal",
            text="Gutschrift PayPal Europe Zalando Payments 1049476150527"),
        row(24, 3000.0, "Employer", TxKind.INCOME, "salary"),
    ])
    paypal(db, txs=[row(9, 171.04, "Zalando", TxKind.REFUND, "refunds_returns", ref="1049476150527", channel="PayPal")])
    assert linking.auto_mirror_paypal(db) == 1
    m = calculate_metrics(db, "Apr", 2026)
    assert m["gross_income"] == pytest.approx(3000.0 + 171.04)  # the refund once, not twice


def test_money_from_friends_is_never_matched_to_a_bank_credit_automatically(db):
    sparkasse(db, txs=[row(15, 100.0, "Lena", TxKind.INCOME, "other_income", text="Lena Ueberweisung"),
                       row(1, -800.0, "Landlord", category="rent")])
    paypal(db, txs=[row(15, 100.0, "Lena", TxKind.INCOME, "other_income", channel="PayPal")])
    assert linking.auto_mirror_paypal(db) == 0
