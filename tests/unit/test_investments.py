import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, DBBankStatement, DBBankTransaction
from services import investments
from services.investments import UNKNOWN, InvestmentError, instrument_code, summary

D = datetime.date
TODAY = D(2026, 3, 20)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def statement(db, bank, month="Jan", year=2026):
    st = DBBankStatement(bank=bank, month=month, year=year, starting_balance=0, closing_balance=0, transactions=[])
    db.add(st)
    db.flush()
    return st


def book(db, st, date, amount, who, text="", kind="investment", category=None):
    tx = DBBankTransaction(statement_id=st.id, booking_date=date, amount=amount, counterparty=who,
                           description=text, kind=kind, category=category)
    db.add(tx)
    db.commit()
    return tx


def n26_buy(db, st, date, amount):
    return book(db, st, date, -amount, "Equities Settlement account", "N26 payment hold for buy, paymentId: abc-123")


def commerz_buy(db, st, date, amount, fund, wkn):
    return book(db, st, date, -amount, fund, f"WP-KAUF GESCH.TG.02.01.2026 V. 02.01.2026 72/005128 X WPKNR: {wkn}")


# ── what a booking says it bought ─────────────────────────────────────────────────────────────
def test_a_wkn_or_isin_in_the_booking_identifies_the_instrument():
    assert instrument_code("WP-KAUF GESCH.TG.02.01.2026 AGIF-A.GL.ART.INTEL.A EO WPKNR: A2DKAR") == "A2DKAR"
    assert instrument_code("Kauf ETF IE00B4L5Y983 iShares Core MSCI World") == "IE00B4L5Y983"
    assert instrument_code("N26 payment hold for buy, paymentId: 300b554a-e35e-4bb7-8a12-95bbbae63e6a") is None
    assert instrument_code("") is None


# ── totals ────────────────────────────────────────────────────────────────────────────────────
def test_buys_add_up_and_a_sell_is_money_coming_back(db):
    st = statement(db, "N26")
    n26_buy(db, st, D(2026, 1, 2), 10.0)
    n26_buy(db, st, D(2026, 1, 5), 25.0)
    book(db, st, D(2026, 1, 23), 0.03, "Equities Settlement account", "N26 unconditional payment for sell")
    result = summary(db, "N26", TODAY)
    assert result["totals"]["bought"] == 35.0 and result["totals"]["sold"] == 0.03
    assert result["totals"]["net"] == 34.97
    assert (result["totals"]["first_date"], result["totals"]["last_date"]) == ("2026-01-02", "2026-01-23")


def test_the_brokers_are_kept_apart_and_the_overview_adds_them(db):
    n26, cz = statement(db, "N26"), statement(db, "Commerzbank")
    n26_buy(db, n26, D(2026, 1, 2), 10.0)
    commerz_buy(db, cz, D(2026, 1, 5), 24.7, "AGIF Allianz Global AI", "A2DKAR")
    assert summary(db, "N26", TODAY)["totals"]["net"] == 10.0
    assert summary(db, "Commerzbank", TODAY)["totals"]["net"] == 24.7
    overview = summary(db, None, TODAY)
    assert overview["totals"]["net"] == 34.7
    assert {b["broker"]: b["net"] for b in overview["brokers"]} == {"N26": 10.0, "Commerzbank": 24.7}
    assert overview["months"][0]["by_broker"] == {"N26": 10.0, "Commerzbank": 24.7}
    assert overview["bookings"] == []  # the list of single bookings belongs to a broker's page


def test_only_investment_bookings_count_not_spending_or_transfers(db):
    st = statement(db, "N26")
    n26_buy(db, st, D(2026, 1, 2), 10.0)
    book(db, st, D(2026, 1, 3), -30.0, "Rewe", "groceries", kind="spend")
    book(db, st, D(2026, 1, 4), -300.0, "Abir", "transfer", kind="internal_transfer")
    assert summary(db, None, TODAY)["totals"]["net"] == 10.0


def test_a_broker_without_bookings_still_has_its_tab(db):
    result = summary(db, None, TODAY)
    assert [b["broker"] for b in result["brokers"]] == ["N26", "Commerzbank"]
    assert result["totals"]["net"] == 0 and result["months"] == [] and result["years"] == []
    assert summary(db, "N26", TODAY)["instruments"] == []


def test_a_bank_with_direct_fund_orders_gets_its_own_tab(db):
    book(db, statement(db, "Sparkasse"), D(2026, 1, 24), -120.0, "Abir", "Auftrag online fonds")
    assert [b["broker"] for b in summary(db, None, TODAY)["brokers"]] == ["N26", "Commerzbank", "Sparkasse"]


def test_an_unknown_broker_is_refused(db):
    with pytest.raises(InvestmentError):
        summary(db, "Trade Republic", TODAY)


# ── months and years ──────────────────────────────────────────────────────────────────────────
def test_every_month_up_to_today_is_listed_and_a_missing_statement_is_not_a_zero(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 10.0)
    n26_buy(db, statement(db, "N26", "Mar"), D(2026, 3, 2), 10.0)  # no February statement uploaded
    months = summary(db, "N26", TODAY)["months"]
    assert [(m["label"], m["net"], m["count"], m["covered"]) for m in months] == [
        ("Jan 26", 10.0, 1, True), ("Feb 26", 0, 0, False), ("Mar 26", 10.0, 1, True)]


def test_a_statement_without_buys_is_a_real_zero(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 10.0)
    statement(db, "N26", "Feb")  # uploaded, nothing invested that month
    feb = summary(db, "N26", TODAY)["months"][1]
    assert (feb["net"], feb["covered"], feb["statements"]) == (0, True, ["N26"])


def test_the_month_is_covered_by_another_broker_only_in_the_overview(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 10.0)
    commerz_buy(db, statement(db, "Commerzbank", "Feb"), D(2026, 2, 5), 24.7, "AGIF", "A2DKAR")
    n26_view = {m["label"]: m["covered"] for m in summary(db, "N26", TODAY)["months"]}
    overview = {m["label"]: m["covered"] for m in summary(db, None, TODAY)["months"]}
    assert n26_view == {"Jan 26": True, "Feb 26": False, "Mar 26": False}  # Commerzbank's February is not N26's
    assert overview["Feb 26"] is True


def test_a_booking_filed_under_the_next_month_still_counts_that_month(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 2, 1), 10.0)  # 1 Feb on the January statement
    feb = summary(db, "N26", TODAY)["months"][0]
    assert (feb["label"], feb["covered"]) == ("Feb 26", True)


def test_years_show_the_total_and_the_monthly_average_over_the_months_since_the_first_buy(db):
    n26_buy(db, statement(db, "N26", "Nov", 2025), D(2025, 11, 2), 30.0)
    statement(db, "N26", "Dec", 2025)
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 60.0)
    statement(db, "N26", "Feb")
    statement(db, "N26", "Mar")
    years = {y["year"]: y for y in summary(db, "N26", TODAY)["years"]}
    assert (years[2025]["net"], years[2025]["months"], years[2025]["avg_per_month"]) == (30.0, 2, 15.0)  # Nov, Dec
    assert (years[2026]["net"], years[2026]["months"], years[2026]["avg_per_month"]) == (60.0, 3, 20.0)  # Jan..Mar


def test_months_not_uploaded_yet_do_not_dilute_the_average(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 60.0)
    statement(db, "N26", "Mar")  # February was never uploaded
    year = summary(db, "N26", TODAY)["years"][0]
    assert (year["months"], year["avg_per_month"]) == (2, 30.0)


def test_this_year_and_the_average_over_months_that_have_a_statement(db):
    n26_buy(db, statement(db, "N26", "Dec", 2025), D(2025, 12, 2), 100.0)
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 100.0)
    totals = summary(db, "N26", TODAY)["totals"]
    assert totals["this_year"] == 100.0
    assert (totals["avg_per_month_12"], totals["months_with_statement"]) == (100.0, 2)  # not 200 over 4 or 12


def test_the_overview_average_adds_each_brokers_own_average(db):
    n26_buy(db, statement(db, "N26", "Jan"), D(2026, 1, 2), 60.0)
    commerz_buy(db, statement(db, "Commerzbank", "Feb"), D(2026, 2, 5), 30.0, "AGIF", "A2DKAR")
    overview = summary(db, None, TODAY)
    # N26 put in 60 in its one month, Commerzbank 30 in its one month: 90 a month together (not 90 / 2).
    assert overview["totals"]["avg_per_month_12"] == 90.0
    assert overview["years"][0]["avg_per_month"] == 90.0
    assert summary(db, "N26", TODAY)["totals"]["avg_per_month_12"] == 60.0


# ── what was bought ───────────────────────────────────────────────────────────────────────────
def test_commerzbank_plans_are_read_from_the_bookings_and_n26_stays_unknown(db):
    cz, n26 = statement(db, "Commerzbank"), statement(db, "N26")
    for month in (1, 2):
        commerz_buy(db, cz, D(2026, month, 5), 24.7, "AGIF Allianz Global AI", "A2DKAR")
        commerz_buy(db, cz, D(2026, month, 6), 24.8, "Pictet Indian Equities", "A0J4DE")
    n26_buy(db, n26, D(2026, 1, 2), 10.0)
    result = summary(db, None, TODAY)
    by_name = {i["name"]: i for i in result["instruments"]}
    assert set(by_name) == {"AGIF Allianz Global AI", "Pictet Indian Equities", UNKNOWN}
    agif = by_name["AGIF Allianz Global AI"]
    assert (agif["code"], agif["net"], agif["buys"], agif["per_month"]) == ("A2DKAR", 49.4, 2, 24.7)
    assert result["instruments"][-1]["name"] == UNKNOWN  # unknown always last
    assert result["unknown"] == {"net": 10.0, "count": 1}
    assert result["months"][0]["by_instrument"][UNKNOWN] == 10.0


def test_shares_add_up_to_a_hundred_percent(db):
    cz = statement(db, "Commerzbank")
    commerz_buy(db, cz, D(2026, 1, 5), 25.0, "A", "AAAAAA")
    commerz_buy(db, cz, D(2026, 1, 6), 75.0, "B", "BBBBBB")
    shares = {i["name"]: i["share_pct"] for i in summary(db, "Commerzbank", TODAY)["instruments"]}
    assert shares == {"B": 75.0, "A": 25.0}


# ── costs and money received ──────────────────────────────────────────────────────────────────
def test_depot_fees_taxes_and_dividends_are_shown_apart_from_the_investment(db):
    cz, n26 = statement(db, "Commerzbank"), statement(db, "N26")
    book(db, cz, D(2026, 1, 22), -0.96, "Commerzbank", "Steuerbelastung auf Vorabpauschale", kind="spend", category="taxes_fees")
    book(db, cz, D(2026, 1, 30), -4.9, "Commerzbank", "Kontoführung Grundpreis", kind="fee", category="bank_fees")
    book(db, cz, D(2026, 1, 31), 1.2, "Fund", "Ausschüttung", kind="income")
    book(db, n26, D(2026, 4, 1), 0.19, "N26 Equities", "Equities Settlement account cash dividend", kind="income")
    book(db, n26, D(2026, 1, 8), -30.0, "Rewe", "groceries", kind="spend", category="groceries")  # daily life: ignored
    book(db, n26, D(2026, 1, 9), 500.0, "Employer", "salary", kind="income")  # not the depot: ignored
    result = summary(db, None, TODAY)
    assert result["costs"]["total"] == 5.86 and len(result["costs"]["items"]) == 2
    assert result["received"]["total"] == 1.39 and len(result["received"]["items"]) == 2
    assert result["totals"]["net"] == 0  # none of this is "invested"


def test_a_grocery_fee_on_a_non_depot_statement_is_not_a_depot_cost(db):
    book(db, statement(db, "Sparkasse"), D(2026, 1, 5), -9.95, "Sparkasse", "Kontoführung", kind="fee")
    assert summary(db, None, TODAY)["costs"]["total"] == 0


# ── the single bookings ───────────────────────────────────────────────────────────────────────
def test_a_broker_page_lists_its_bookings_newest_first(db):
    st = statement(db, "N26")
    n26_buy(db, st, D(2026, 1, 2), 10.0)
    n26_buy(db, st, D(2026, 1, 9), 25.0)
    rows = summary(db, "N26", TODAY)["bookings"]
    assert [(r["date"], r["amount"], r["instrument"]) for r in rows] == [("2026-01-09", 25.0, UNKNOWN), ("2026-01-02", 10.0, UNKNOWN)]


def test_the_module_is_read_only(db):
    st = statement(db, "N26")
    n26_buy(db, st, D(2026, 1, 2), 10.0)
    before = db.query(DBBankTransaction).count()
    summary(db, None, TODAY)
    assert db.query(DBBankTransaction).count() == before and investments.BROKERS == ("N26", "Commerzbank", "Sparkasse")


# ── deciding by hand that a booking is a transfer, not an investment ─────────────────────────
def sparkasse_fund_order(db):
    st = statement(db, "Sparkasse", "Apr")
    return book(db, st, D(2026, 4, 24), -120.0, "Abir", "Auftrag online Abir fonds DATUM 24.04.2026")


def test_a_booking_moved_out_of_the_investments_no_longer_counts_and_can_come_back(db):
    tx = sparkasse_fund_order(db)
    n26_buy(db, statement(db, "N26", "Apr"), D(2026, 4, 7), 10.0)
    assert summary(db, None, TODAY)["totals"]["net"] == 130.0

    investments.set_booking_kind(db, tx.id, "internal_transfer")
    moved = summary(db, None, TODAY)
    assert moved["totals"]["net"] == 10.0
    assert [b["broker"] for b in moved["brokers"]] == ["N26", "Commerzbank"]  # Sparkasse has no investments now
    assert [(m["id"], m["amount"], m["broker"]) for m in moved["moved_out"]] == [(tx.id, 120.0, "Sparkasse")]

    investments.set_booking_kind(db, tx.id, "investment")
    back = summary(db, None, TODAY)
    assert back["totals"]["net"] == 130.0 and back["moved_out"] == []


def test_moving_a_booking_out_is_remembered_as_the_households_decision(db):
    tx = sparkasse_fund_order(db)
    investments.set_booking_kind(db, tx.id, "internal_transfer")
    db.refresh(tx)
    assert (tx.kind, tx.link_status, tx.link_reason) == ("internal_transfer", "confirmed", investments.MANUAL_REASON)
    assert tx.category is None and tx.transfer_group is None


def test_moved_out_bookings_are_listed_per_broker(db):
    tx = sparkasse_fund_order(db)
    investments.set_booking_kind(db, tx.id, "internal_transfer")
    assert len(summary(db, "Sparkasse", TODAY)["moved_out"]) == 1
    assert summary(db, "N26", TODAY)["moved_out"] == []


def test_only_investment_bookings_can_be_moved_out(db):
    st = statement(db, "N26")
    spend = book(db, st, D(2026, 1, 3), -30.0, "Rewe", "groceries", kind="spend")
    with pytest.raises(InvestmentError):
        investments.set_booking_kind(db, spend.id, "internal_transfer")


def test_a_transfer_the_app_paired_itself_cannot_be_turned_into_an_investment(db):
    st = statement(db, "Sparkasse")
    paired = book(db, st, D(2026, 1, 5), -300.0, "Abir", "to N26", kind="internal_transfer")
    paired.transfer_group = paired.id
    paired.link_reason = "auto: same amount, only possible partner"
    db.commit()
    with pytest.raises(InvestmentError):
        investments.set_booking_kind(db, paired.id, "investment")


def test_a_plain_transfer_without_a_manual_mark_cannot_be_moved_into_the_investments(db):
    st = statement(db, "Sparkasse")
    plain = book(db, st, D(2026, 1, 5), -300.0, "Abir", "to N26", kind="internal_transfer")
    with pytest.raises(InvestmentError):
        investments.set_booking_kind(db, plain.id, "investment")


def test_bookings_on_other_banks_are_not_changed_here(db):
    paypal = book(db, statement(db, "PayPal"), D(2026, 1, 5), -20.0, "Someone", "x", kind="investment")
    with pytest.raises(InvestmentError):
        investments.set_booking_kind(db, paypal.id, "internal_transfer")


def test_an_unknown_kind_or_booking_is_refused(db):
    tx = sparkasse_fund_order(db)
    with pytest.raises(InvestmentError):
        investments.set_booking_kind(db, tx.id, "spend")
    with pytest.raises(LookupError):
        investments.set_booking_kind(db, 999, "internal_transfer")


def test_the_route_reports_success_and_refusals():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from database.session import get_db
    from routes.investments import router

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    with factory() as session:
        tx_id = sparkasse_fund_order(session).id
    ok = client.patch(f"/investments/bookings/{tx_id}", json={"kind": "internal_transfer"})
    assert ok.status_code == 200 and ok.json() == {"id": tx_id, "kind": "internal_transfer"}
    assert client.patch(f"/investments/bookings/{tx_id}", json={"kind": "spend"}).status_code == 400
    assert client.patch("/investments/bookings/999", json={"kind": "internal_transfer"}).status_code == 404
