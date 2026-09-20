import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, DBBankStatement, DBBankTransaction
from database.session import get_db
from routes.investments import router
from services import investment_plans as plans
from services import investments
from services.investment_brokers import MANUAL, UNKNOWN
from services.investment_plans import PlanIn

D = datetime.date
TODAY = D(2026, 10, 5)
SEP_START = D(2026, 9, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def statement(db, bank="N26", month="Sep", year=2026):
    st = DBBankStatement(bank=bank, month=month, year=year, starting_balance=0, closing_balance=0, transactions=[])
    db.add(st)
    db.flush()
    return st


def buy(db, st, date, amount, uid="a"):
    tx = DBBankTransaction(statement_id=st.id, booking_date=date, amount=-amount, counterparty="Equities Settlement account",
                           description=f"N26 payment hold for buy, paymentId: {uid}-{date}-{amount}", kind="investment")
    db.add(tx)
    db.commit()
    return tx


def plan(db, instrument, amount, frequency="biweekly", anchor=None, start=SEP_START, **extra):
    return plans.create_plan(db, PlanIn("N26", instrument, amount, frequency, anchor_date=anchor, start_date=start, **extra))


def result(db, broker="N26"):
    return investments.summary(db, broker, TODAY)


def labels(result_):
    return {(b["date"], b["amount"]): (b["instrument"], b["source"]) for b in result_["bookings"]}


# ── plans with a known execution day ──────────────────────────────────────────────────────────
def test_buys_are_named_by_the_plan_that_executes_that_day(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    plan(db, "EQQQ", 10, anchor=D(2026, 9, 15))
    plan(db, "Bitcoin", 5, "monthly", anchor=D(2026, 9, 10))
    st = statement(db)
    for date, amount in [(D(2026, 9, 8), 10), (D(2026, 9, 10), 5), (D(2026, 9, 16), 10), (D(2026, 9, 22), 10), (D(2026, 9, 29), 10)]:
        buy(db, st, date, amount)
    got = labels(result(db))
    assert got[("2026-09-08", 10.0)] == ("FTSE", "plan")
    assert got[("2026-09-10", 5.0)] == ("Bitcoin", "plan")
    assert got[("2026-09-16", 10.0)] == ("EQQQ", "plan")  # a day after its execution day
    assert got[("2026-09-22", 10.0)] == ("FTSE", "plan")
    assert got[("2026-09-29", 10.0)] == ("EQQQ", "plan")
    named = {i["name"]: i["net"] for i in result(db)["instruments"]}
    assert named == {"FTSE": 20.0, "EQQQ": 20.0, "Bitcoin": 5.0}


def test_two_plans_of_the_same_amount_on_the_same_day_each_get_exactly_one_buy(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    plan(db, "NRG", 10, anchor=D(2026, 9, 8))
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10, "x")
    buy(db, st, D(2026, 9, 8), 10, "y")
    assert {i["name"]: (i["net"], i["buys"]) for i in result(db)["instruments"]} == {"FTSE": (10.0, 1), "NRG": (10.0, 1)}


def test_the_closest_booking_wins_and_one_booking_serves_only_one_plan_day(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8), frequency="weekly")  # executes 8th, 15th, 22nd
    st = statement(db)
    buy(db, st, D(2026, 9, 9), 10)  # one day after the 8th
    buy(db, st, D(2026, 9, 14), 10)  # one day before the 15th
    got = labels(result(db))
    assert got[("2026-09-09", 10.0)] == ("FTSE", "plan") and got[("2026-09-14", 10.0)] == ("FTSE", "plan")


def test_a_booking_more_than_three_days_from_any_execution_is_not_the_plans(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    st = statement(db)
    buy(db, st, D(2026, 9, 11), 10, "near")  # 3 days: still the plan's
    buy(db, st, D(2026, 9, 18), 10, "far")  # 10 days after the 8th, 4 before the 22nd: nobody's
    got = labels(result(db))
    assert got[("2026-09-11", 10.0)] == ("FTSE", "plan")
    assert got[("2026-09-18", 10.0)] == (MANUAL, "manual_buy")


def test_a_different_amount_is_a_manual_buy_while_plans_are_running(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10)
    buy(db, st, D(2026, 9, 12), 47.5)  # bought by hand on a dip
    out = result(db)
    assert labels(out)[("2026-09-12", 47.5)] == (MANUAL, "manual_buy")
    assert out["manual"] == {"net": 47.5, "count": 1}
    assert [i["name"] for i in out["instruments"]] == ["FTSE", MANUAL]  # named first, manual after


# ── the check of the plans against what was booked ────────────────────────────────────────────
def test_an_expected_buy_that_never_came_is_reported_but_only_where_the_statement_reaches(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))  # 8th, 22nd; the next on 6 October is not in the statement yet
    plan(db, "EQQQ", 10, anchor=D(2026, 9, 15), start=D(2026, 9, 2))  # 15th, 29th: the 29th could still come in October
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10)
    buy(db, st, D(2026, 9, 15), 10)
    check = result(db)["plan_check"]["N26"]
    assert [(m["date"], m["instrument"]) for m in check["missed"]] == [("2026-09-22", "FTSE")]
    assert (check["expected"], check["matched"]) == (3, 2)  # 8th, 15th, 22nd; not the 29th


def test_no_statement_means_nothing_can_be_called_missing(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    check = result(db)["plan_check"]["N26"]
    assert (check["expected"], check["missed"]) == (0, [])


def test_the_check_says_how_many_plans_have_a_known_day(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    plan(db, "NRG", 10)
    plan(db, "Old", 10, start=D(2026, 1, 1), end_date=D(2026, 2, 1))  # ended: does not count
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10)
    check = result(db)["plan_check"]["N26"]
    assert (check["anchored_plans"], check["unanchored_plans"]) == (1, 1)


# ── plans without a known day: only the amount can say ────────────────────────────────────────
def test_an_amount_that_only_one_plan_has_names_the_buy(db):
    plan(db, "FTSE", 35)
    plan(db, "Bitcoin", 5, "monthly")
    st = statement(db)
    buy(db, st, D(2026, 9, 9), 35)
    buy(db, st, D(2026, 9, 10), 5)
    got = labels(result(db))
    assert got[("2026-09-09", 35.0)] == ("FTSE", "plan_amount") and got[("2026-09-10", 5.0)] == ("Bitcoin", "plan_amount")


def test_an_amount_shared_by_several_plans_is_not_guessed(db):
    plan(db, "Allianz", 10)
    plan(db, "NRG", 10)
    plan(db, "LLY", 10)
    st = statement(db)
    buy(db, st, D(2026, 9, 9), 10)
    out = result(db)
    booking = out["bookings"][0]
    assert (booking["instrument"], booking["source"]) == (UNKNOWN, "ambiguous")
    assert booking["candidates"] == ["Allianz", "LLY", "NRG"]
    assert out["plan_check"]["N26"]["ambiguous"] == {"count": 1, "net": 10.0}


def test_two_plans_of_one_instrument_and_amount_are_not_ambiguous(db):
    plan(db, "FTSE", 10)
    plan(db, "FTSE", 10)
    buy(db, statement(db), D(2026, 9, 9), 10)
    assert result(db)["bookings"][0]["instrument"] == "FTSE"


def test_before_the_plans_started_nothing_is_guessed(db):
    plan(db, "FTSE", 35)  # from 1 September
    jan = statement(db, month="Jan")
    sep = statement(db)
    buy(db, jan, D(2026, 1, 9), 35)
    buy(db, sep, D(2026, 9, 9), 35)
    got = labels(result(db))
    assert got[("2026-01-09", 35.0)] == (UNKNOWN, "unknown")  # no plan was known to run then
    assert got[("2026-09-09", 35.0)] == ("FTSE", "plan_amount")


def test_a_suspended_plan_no_longer_explains_later_buys(db):
    p = plan(db, "FTSE", 35)
    plans.suspend_plan(db, p.id, D(2026, 9, 20))
    st = statement(db)
    buy(db, st, D(2026, 9, 9), 35)
    buy(db, st, D(2026, 9, 25), 35)
    got = labels(result(db))
    assert got[("2026-09-09", 35.0)][0] == "FTSE"
    assert got[("2026-09-25", 35.0)][0] == UNKNOWN  # after the suspension no plan covers the day


def test_known_and_unknown_days_work_side_by_side(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    plan(db, "Bitcoin", 5, "monthly")
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10)
    buy(db, st, D(2026, 9, 10), 5)
    got = labels(result(db))
    assert (got[("2026-09-08", 10.0)][1], got[("2026-09-10", 5.0)][1]) == ("plan", "plan_amount")


# ── what the household typed ──────────────────────────────────────────────────────────────────
def test_a_typed_ticker_wins_over_every_plan_and_frees_the_planned_slot(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    st = statement(db)
    early = buy(db, st, D(2026, 9, 7), 10, "early")  # would be taken for FTSE's 8th
    late = buy(db, st, D(2026, 9, 9), 10, "late")
    assert labels(result(db))[("2026-09-07", 10.0)][0] == "FTSE"  # the closest to the 8th
    investments.assign_instrument(db, early.id, "  tsla ")
    got = labels(result(db))
    assert got[("2026-09-07", 10.0)] == ("tsla", "manual")
    assert got[("2026-09-09", 10.0)] == ("FTSE", "plan")  # the plan's day is now explained by the other booking
    assert late.id


def test_what_was_typed_survives_reading_the_statement_again(db):
    st = statement(db)
    tx = buy(db, st, D(2026, 9, 12), 47.5)
    investments.assign_instrument(db, tx.id, "TSLA")
    db.delete(tx)  # a re-read removes the booking and stores it again with a new id
    db.commit()
    buy(db, st, D(2026, 9, 20), 5, "other")  # something else is stored first, so the id cannot be reused
    again = buy(db, st, D(2026, 9, 12), 47.5)
    assert again.id != tx.id
    assert labels(result(db))[("2026-09-12", 47.5)] == ("TSLA", "manual")


def test_clearing_what_was_typed_lets_the_plans_decide_again(db):
    plan(db, "FTSE", 35)
    tx = buy(db, statement(db), D(2026, 9, 9), 35)
    investments.assign_instrument(db, tx.id, "TSLA")
    assert result(db)["bookings"][0]["instrument"] == "TSLA"
    investments.clear_instrument(db, tx.id)
    assert result(db)["bookings"][0]["instrument"] == "FTSE"


def test_a_sell_can_be_labelled_and_is_never_taken_for_a_plan(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    st = statement(db)
    sell = DBBankTransaction(statement_id=st.id, booking_date=D(2026, 9, 8), amount=10.0, counterparty="Equities Settlement account",
                             description="N26 unconditional payment for sell, paymentId: s1", kind="investment")
    db.add(sell)
    db.commit()
    assert result(db)["bookings"][0]["instrument"] == UNKNOWN and result(db)["totals"]["net"] == -10.0
    investments.assign_instrument(db, sell.id, "TSLA")
    assert result(db)["bookings"][0]["instrument"] == "TSLA"


def test_typed_names_are_offered_again_together_with_the_plans_names(db):
    plan(db, "FTSE", 10)
    tx = buy(db, statement(db), D(2026, 9, 12), 47.5)
    investments.assign_instrument(db, tx.id, "TSLA")
    assert result(db)["known_instruments"] == ["FTSE", "TSLA"]


def test_only_investment_bookings_on_brokers_can_be_labelled(db):
    st = statement(db)
    spend = DBBankTransaction(statement_id=st.id, booking_date=D(2026, 9, 3), amount=-30, counterparty="Rewe", description="x", kind="spend")
    paypal = DBBankTransaction(statement_id=statement(db, "PayPal").id, booking_date=D(2026, 9, 3), amount=-30, counterparty="X",
                               description="x", kind="investment")
    db.add_all([spend, paypal])
    db.commit()
    for bad in (spend.id, paypal.id):
        with pytest.raises(investments.InvestmentError):
            investments.assign_instrument(db, bad, "TSLA")
    with pytest.raises(investments.InvestmentError):
        investments.assign_instrument(db, buy(db, st, D(2026, 9, 4), 10).id, "   ")
    with pytest.raises(LookupError):
        investments.assign_instrument(db, 999, "TSLA")


# ── funds the booking names, and the summary around it ────────────────────────────────────────
def test_a_fund_named_by_the_booking_is_left_alone_by_plans(db):
    plan(db, "Something else", 24.7)
    cz = statement(db, "Commerzbank", "Jan")
    tx = DBBankTransaction(statement_id=cz.id, booking_date=D(2026, 1, 5), amount=-24.7, counterparty="AGIF Allianz Global AI",
                           description="WP-KAUF ... WPKNR: A2DKAR", kind="investment")
    db.add(tx)
    db.commit()
    assert result(db, "Commerzbank")["bookings"][0]["instrument"] == "AGIF Allianz Global AI"


def test_the_instruments_are_grouped_by_name_and_their_shares_add_up(db):
    plan(db, "FTSE", 10, anchor=D(2026, 9, 8))
    plan(db, "NRG", 30, anchor=D(2026, 9, 10))
    st = statement(db)
    buy(db, st, D(2026, 9, 8), 10)
    buy(db, st, D(2026, 9, 10), 30)
    out = result(db)
    assert {i["name"]: i["share_pct"] for i in out["instruments"]} == {"NRG": 75.0, "FTSE": 25.0}
    assert out["months"][0]["by_instrument"] == {"FTSE": 10.0, "NRG": 30.0}


def test_the_overview_uses_the_plans_too(db):
    plan(db, "FTSE", 35)
    buy(db, statement(db), D(2026, 9, 9), 35)
    overview = investments.summary(db, None, TODAY)
    assert [i["name"] for i in overview["instruments"]] == ["FTSE"]


# ── the API ───────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override
    with factory() as session:
        tx_id = buy(session, statement(session), D(2026, 9, 12), 47.5).id
    return TestClient(app), tx_id


def test_the_api_types_and_forgets_a_ticker(client):
    api, tx_id = client
    ok = api.put(f"/investments/bookings/{tx_id}/instrument", json={"instrument": "TSLA"})
    assert ok.status_code == 200 and ok.json() == {"id": tx_id, "instrument": "TSLA"}
    assert api.get("/investments/summary?broker=N26").json()["bookings"][0]["instrument"] == "TSLA"
    assert api.delete(f"/investments/bookings/{tx_id}/instrument").status_code == 204
    assert api.get("/investments/summary?broker=N26").json()["bookings"][0]["instrument"] == UNKNOWN


def test_the_api_explains_refusals(client):
    api, tx_id = client
    assert api.put(f"/investments/bookings/{tx_id}/instrument", json={"instrument": " "}).status_code == 400
    assert api.put("/investments/bookings/999/instrument", json={"instrument": "TSLA"}).status_code == 404
    assert api.delete("/investments/bookings/999/instrument").status_code == 404
