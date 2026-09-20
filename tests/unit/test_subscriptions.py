import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction
from services import subscriptions as subs
from services.categories import seed_categories

D = datetime.date


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def statement(db, bank="Sparkasse"):
    st = DBBankStatement(bank=bank, month="Jan", year=2026, starting_balance=0, closing_balance=0, transactions=[])
    db.add(st)
    db.flush()
    return st


def pay(db, st, who, date, amount, category=None, kind="spend", **extra):
    tx = DBBankTransaction(statement_id=st.id, booking_date=date, amount=-abs(amount), counterparty=who,
                           description=who, kind=kind, category=category, **extra)
    db.add(tx)
    db.flush()
    return tx


def by_name(result):
    return {i["name"]: i for i in result["items"]}


def test_the_same_payee_and_amount_every_month_is_a_confirmed_subscription(db):
    st = statement(db)
    for month in (1, 2, 3):
        pay(db, st, "Netflix", D(2026, month, 5), 12.99, "subscriptions")
    db.commit()
    netflix = by_name(subs.subscriptions(db))["Netflix"]
    assert (netflix["frequency"], netflix["evidence"], netflix["confidence"]) == ("monthly", "pattern", "confirmed")
    assert (netflix["monthly_cost"], netflix["yearly_cost"], netflix["payments"]) == (12.99, 155.88, 3)
    assert netflix["next_expected"] == "2026-04-04"


def test_two_payments_are_only_likely(db):
    st = statement(db)
    pay(db, st, "Spotify", D(2026, 1, 9), 10.99, "subscriptions")
    pay(db, st, "Spotify", D(2026, 2, 9), 10.99, "subscriptions")
    db.commit()
    assert by_name(subs.subscriptions(db))["Spotify"]["confidence"] == "likely"


def test_a_yearly_payment_is_recognised_and_costs_a_twelfth_per_month(db):
    st = statement(db)
    pay(db, st, "Amazon Prime", D(2025, 3, 2), 89.90, "subscriptions")
    pay(db, st, "Amazon Prime", D(2026, 3, 2), 89.90, "subscriptions")
    db.commit()
    prime = by_name(subs.subscriptions(db))["Amazon Prime"]
    assert (prime["frequency"], prime["monthly_cost"]) == ("yearly", 7.49)


def test_shopping_with_varying_amounts_is_not_a_subscription(db):
    st = statement(db)
    for month, amount in ((1, 43.20), (2, 87.10), (3, 12.40)):
        pay(db, st, "Kaufland", D(2026, month, 14), amount, "groceries")
    db.commit()
    assert "Kaufland" not in by_name(subs.subscriptions(db))


def test_noise_in_the_payee_name_does_not_split_it(db):
    st = statement(db)
    pay(db, st, "Netflix International B.V.", D(2026, 1, 5), 12.99, "subscriptions")
    pay(db, st, "NETFLIX.COM 4711", D(2026, 2, 5), 12.99, "subscriptions")
    db.commit()
    assert len(subs.subscriptions(db)["items"]) == 1


def test_a_price_rise_is_reported(db):
    st = statement(db)
    pay(db, st, "Netflix", D(2026, 1, 5), 12.99, "subscriptions")
    pay(db, st, "Netflix", D(2026, 2, 5), 12.99, "subscriptions")
    pay(db, st, "Netflix", D(2026, 3, 5), 13.99, "subscriptions")
    db.commit()
    result = subs.subscriptions(db)
    assert by_name(result)["Netflix"]["price_change"] == {"from": 12.99, "to": 13.99}
    assert result["summary"]["price_rises"] == 1


def test_seen_once_in_a_fixed_category_is_assumed_monthly(db):
    st = statement(db)
    pay(db, st, "Vodafone", D(2026, 4, 3), 25.0, "internet_phone")
    pay(db, st, "Kaufland", D(2026, 4, 5), 25.0, "groceries")  # not a fixed cost: ignored
    db.commit()
    result = subs.subscriptions(db)
    vodafone = by_name(result)["Vodafone"]
    assert (vodafone["evidence"], vodafone["confidence"], vodafone["frequency"]) == ("category", "assumed", "monthly")
    assert "Kaufland" not in by_name(result)
    assert result["summary"]["assumed_monthly"] == 25.0


def test_bills_and_subscriptions_are_told_apart(db):
    st = statement(db)
    pay(db, st, "Landlord", D(2026, 4, 1), 800.0, "rent")
    pay(db, st, "Netflix", D(2026, 4, 5), 12.99, "subscriptions")
    db.commit()
    items = by_name(subs.subscriptions(db))
    assert (items["Landlord"]["section"], items["Netflix"]["section"]) == ("bill", "subscription")


def test_shopping_that_has_a_receipt_and_transfers_never_count(db):
    st = statement(db)
    pay(db, st, "Gym", D(2026, 1, 1), 30.0, "fitness", kind="internal_transfer")
    pay(db, st, "Gym", D(2026, 2, 1), 30.0, "fitness", kind="investment")
    db.commit()
    assert subs.subscriptions(db)["items"] == []


def test_a_paypal_row_replaces_the_opaque_bank_line_it_explains(db):
    bank, paypal = statement(db), statement(db, "PayPal")
    line = pay(db, bank, "PayPal Europe", D(2026, 1, 6), 12.99, "subscriptions")
    detail = pay(db, paypal, "Netflix", D(2026, 1, 5), 12.99, "subscriptions")
    detail.mirror_of = line.id
    db.commit()
    result = subs.subscriptions(db)
    assert [i["name"] for i in result["items"]] == ["Netflix"]  # counted once, under the real name


def test_ended_needs_a_statement_that_reaches_past_the_missing_payment(db):
    st = statement(db)
    for month in (1, 2, 3):
        pay(db, st, "Old gym", D(2026, month, 2), 20.0, "fitness")
    pay(db, st, "Rent", D(2026, 8, 1), 700.0, "rent")  # the statements reach August, no gym payment since March
    pay(db, st, "Netflix", D(2026, 7, 5), 12.99, "subscriptions")
    db.commit()
    result = subs.subscriptions(db)
    assert by_name(result)["Old gym"]["status"] == "ended"
    assert result["summary"]["monthly_total"] == 712.99  # the ended one is not counted
    assert result["statements_reach"] == "2026-08-01"


def test_without_later_statements_nothing_is_called_ended(db):
    st = statement(db)
    for month in (1, 2):
        pay(db, st, "Netflix", D(2026, month, 5), 12.99, "subscriptions")
    db.commit()
    assert by_name(subs.subscriptions(db))["Netflix"]["status"] == "active"


def test_the_household_can_hide_a_false_positive_and_bring_it_back(db):
    st = statement(db)
    pay(db, st, "Netflix", D(2026, 1, 5), 12.99, "subscriptions")
    pay(db, st, "Netflix", D(2026, 2, 5), 12.99, "subscriptions")
    db.commit()
    key = subs.subscriptions(db)["items"][0]["key"]
    subs.set_rule(db, key, None, True)
    hidden = subs.subscriptions(db)
    assert hidden["items"] == [] and hidden["hidden"] == [{"key": key, "name": "Netflix"}]
    assert hidden["summary"]["monthly_total"] == 0
    subs.set_rule(db, key, None, False)
    assert len(subs.subscriptions(db)["items"]) == 1


def test_the_household_can_set_how_often_it_is_charged(db):
    st = statement(db)
    pay(db, st, "Vodafone", D(2026, 4, 3), 120.0, "internet_phone")
    db.commit()
    key = subs.subscriptions(db)["items"][0]["key"]
    subs.set_rule(db, key, "quarterly", False)
    item = subs.subscriptions(db)["items"][0]
    assert (item["frequency"], item["evidence"], item["monthly_cost"]) == ("quarterly", "you", 40.0)


def test_an_unknown_frequency_is_refused(db):
    with pytest.raises(ValueError):
        subs.set_rule(db, "netflix", "fortnightly", False)
