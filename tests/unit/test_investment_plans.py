import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base
from database.session import get_db
from routes.investments import router
from services import investment_plans as plans
from services.investment_plans import PlanError, PlanIn

D = datetime.date
TODAY = D(2026, 9, 20)

# The N26 plans the household runs from September 2026.
CURRENT = [
    ("Bitcoin", 5, "monthly"), ("FTSE", 35, "biweekly"), ("FTSE", 10, "biweekly"),
    ("iBonds Dec 2028 Term", 25, "monthly"), ("NASDAQ US Biotech ETF", 10, "biweekly"),
    ("D-Wave Quantum", 10, "monthly"), ("EQQQ", 10, "biweekly"), ("Ormat Technologies", 10, "biweekly"),
    ("iShares Robotics", 25, "monthly"), ("Allianz", 10, "biweekly"), ("NRG", 10, "biweekly"), ("LLY", 10, "biweekly"),
]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def plan(db, instrument="FTSE", amount=10.0, frequency="biweekly", **extra):
    return plans.create_plan(db, PlanIn("N26", instrument, amount, frequency, **extra))


# ── entering plans ────────────────────────────────────────────────────────────────────────────
def test_the_households_current_twelve_plans_add_up_to_their_monthly_amount(db):
    for name, amount, frequency in CURRENT:
        plan(db, name, amount, frequency, start_date=D(2026, 9, 1))
    summary = plans.list_plans(db, today=TODAY)["summary"]
    # 4 monthly plans = 65; 8 fortnightly plans = 105 every two weeks = 105 * 26 / 12.
    assert summary["active"] == 12
    assert summary["per_month"] == 292.5
    assert summary["per_month_by_broker"] == {"N26": 292.5}


def test_two_plans_may_buy_the_same_instrument_with_different_amounts(db):
    plan(db, "FTSE", 35)
    plan(db, "FTSE", 10)
    assert [p["amount"] for p in plans.list_plans(db, today=TODAY)["plans"]] == [35.0, 10.0]  # biggest first


@pytest.mark.parametrize("bad", [
    {"broker": "Trade Republic"}, {"instrument": "  "}, {"amount": 0}, {"amount": -5}, {"frequency": "daily"},
    {"start_date": D(2026, 9, 10), "end_date": D(2026, 9, 1)},
])
def test_nonsense_is_refused(db, bad):
    fields = {"broker": "N26", "instrument": "FTSE", "amount": 10.0, "frequency": "biweekly", **bad}
    with pytest.raises(PlanError):
        plans.create_plan(db, PlanIn(**fields))


def test_names_and_amounts_are_tidied(db):
    p = plan(db, "  EQQQ  ", 9.999, note="  from the app  ")
    assert (p.instrument, p.amount, p.note) == ("EQQQ", 10.0, "from the app")


# ── when it runs ──────────────────────────────────────────────────────────────────────────────
def test_a_fortnightly_plan_repeats_every_14_days_from_its_known_execution_day(db):
    p = plan(db, anchor_date=D(2026, 9, 8))
    dates = plans.execution_dates(p, D(2026, 9, 1), D(2026, 10, 31))
    assert dates == [D(2026, 9, 8), D(2026, 9, 22), D(2026, 10, 6), D(2026, 10, 20)]


def test_the_known_day_may_be_after_the_period_asked_about(db):
    p = plan(db, anchor_date=D(2026, 10, 6))
    assert plans.execution_dates(p, D(2026, 9, 1), D(2026, 9, 30)) == [D(2026, 9, 8), D(2026, 9, 22)]


def test_a_weekly_plan_runs_every_seven_days(db):
    p = plan(db, frequency="weekly", anchor_date=D(2026, 9, 7))
    assert plans.execution_dates(p, D(2026, 9, 14), D(2026, 9, 28)) == [D(2026, 9, 14), D(2026, 9, 21), D(2026, 9, 28)]


def test_a_monthly_plan_keeps_its_day_and_the_31st_becomes_the_last_day_of_a_short_month(db):
    p = plan(db, frequency="monthly", anchor_date=D(2026, 1, 31))
    assert plans.execution_dates(p, D(2026, 1, 1), D(2026, 4, 30)) == [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]


def test_dates_stay_inside_the_time_the_plan_is_active(db):
    p = plan(db, anchor_date=D(2026, 9, 8), start_date=D(2026, 9, 15), end_date=D(2026, 10, 10))
    assert plans.execution_dates(p, D(2026, 8, 1), D(2026, 12, 31)) == [D(2026, 9, 22), D(2026, 10, 6)]


def test_without_a_known_day_no_dates_can_be_predicted(db):
    assert plans.execution_dates(plan(db), D(2026, 9, 1), D(2026, 12, 31)) == []


def test_status_and_the_next_dates_are_listed(db):
    running = plan(db, "FTSE", anchor_date=D(2026, 9, 8), start_date=D(2026, 9, 1))
    later = plan(db, "EQQQ", start_date=D(2026, 11, 1))
    stopped = plan(db, "NRG", start_date=D(2026, 9, 1), end_date=D(2026, 9, 10))
    by_id = {p["id"]: p for p in plans.list_plans(db, today=TODAY)["plans"]}
    assert by_id[running.id]["status"] == "active" and by_id[running.id]["next_dates"] == ["2026-09-22", "2026-10-06", "2026-10-20"]
    assert by_id[later.id]["status"] == "scheduled" and by_id[stopped.id]["status"] == "ended"
    assert by_id[stopped.id]["next_dates"] == []
    listed = plans.list_plans(db, today=TODAY)
    assert [p["status"] for p in listed["plans"]] == ["active", "scheduled", "ended"]
    assert listed["summary"]["per_month"] == 21.67  # only the active one counts


def test_the_list_can_be_limited_to_one_broker_and_offers_the_names_used(db):
    plan(db, "FTSE")
    plans.create_plan(db, PlanIn("Commerzbank", "Fidelity Technology", 25, "monthly"))
    assert [p["broker"] for p in plans.list_plans(db, "Commerzbank", TODAY)["plans"]] == ["Commerzbank"]
    assert plans.list_plans(db, today=TODAY)["instruments"] == ["Fidelity Technology", "FTSE"]


# ── suspending, resuming and changing keep the history ────────────────────────────────────────
def test_suspending_ends_the_plan_the_day_before_and_keeps_it(db):
    p = plan(db, start_date=D(2026, 9, 1))
    plans.suspend_plan(db, p.id, D(2026, 9, 20))
    assert p.end_date == D(2026, 9, 19)
    assert plans.status_on(p, D(2026, 9, 19)) == "active" and plans.status_on(p, D(2026, 9, 20)) == "ended"


def test_a_plan_that_has_already_ended_cannot_be_suspended_again(db):
    p = plan(db, end_date=D(2026, 8, 1))
    with pytest.raises(PlanError):
        plans.suspend_plan(db, p.id, D(2026, 9, 20))


def test_resuming_opens_a_new_entry_so_the_pause_stays_visible(db):
    p = plan(db, start_date=D(2026, 9, 1), anchor_date=D(2026, 9, 8))
    plans.suspend_plan(db, p.id, D(2026, 10, 1))
    again = plans.resume_plan(db, p.id, D(2026, 12, 1))
    assert again.id != p.id and again.start_date == D(2026, 12, 1) and again.end_date is None
    assert (again.instrument, again.amount, again.frequency, again.anchor_date) == ("FTSE", 10.0, "biweekly", D(2026, 9, 8))
    assert p.end_date == D(2026, 9, 30)  # the first run is unchanged
    assert plans.status_on(p, D(2026, 11, 15)) == "ended" and plans.status_on(again, D(2026, 11, 15)) == "scheduled"


def test_only_an_ended_plan_can_be_resumed(db):
    with pytest.raises(PlanError):
        plans.resume_plan(db, plan(db, start_date=D(2026, 9, 1)).id, TODAY)


def test_changing_the_amount_closes_the_old_plan_and_starts_a_new_one(db):
    old = plan(db, amount=10, start_date=D(2026, 9, 1), anchor_date=D(2026, 9, 8))
    new = plans.change_plan(db, old.id, D(2026, 10, 1), amount=15)
    assert old.end_date == D(2026, 9, 30) and old.amount == 10.0  # what was true then stays true
    assert (new.amount, new.start_date, new.end_date, new.anchor_date) == (15.0, D(2026, 10, 1), None, D(2026, 9, 8))
    assert plans.status_on(old, D(2026, 10, 1)) == "ended" and plans.status_on(new, D(2026, 10, 1)) == "active"


def test_a_rebalance_can_swap_the_instrument(db):
    old = plan(db, "EQQQ", start_date=D(2026, 9, 1))
    new = plans.change_plan(db, old.id, D(2026, 11, 1), instrument="Nasdaq 100")
    assert (old.instrument, new.instrument) == ("EQQQ", "Nasdaq 100")


def test_a_new_rhythm_forgets_the_known_day_because_it_no_longer_fits(db):
    old = plan(db, frequency="biweekly", start_date=D(2026, 9, 1), anchor_date=D(2026, 9, 8))
    assert plans.change_plan(db, old.id, D(2026, 10, 1), frequency="monthly").anchor_date is None
    other = plan(db, frequency="biweekly", start_date=D(2026, 9, 1), anchor_date=D(2026, 9, 8))
    assert plans.change_plan(db, other.id, D(2026, 10, 1), frequency="monthly", anchor_date=D(2026, 10, 5)).anchor_date == D(2026, 10, 5)


def test_a_change_needs_a_day_after_the_start_and_before_the_end(db):
    p = plan(db, start_date=D(2026, 9, 1), end_date=D(2026, 9, 30))
    with pytest.raises(PlanError):
        plans.change_plan(db, p.id, D(2026, 9, 1), amount=20)
    with pytest.raises(PlanError):
        plans.change_plan(db, p.id, D(2026, 10, 15), amount=20)


def test_correcting_a_plan_edits_it_in_place_and_validates(db):
    p = plan(db, "FTS", 10)
    plans.update_plan(db, p.id, {"instrument": " FTSE ", "anchor_date": D(2026, 9, 8)})
    assert (p.instrument, p.anchor_date) == ("FTSE", D(2026, 9, 8))
    plans.update_plan(db, p.id, {"anchor_date": None})
    assert p.anchor_date is None
    with pytest.raises(PlanError):
        plans.update_plan(db, p.id, {"amount": -1})
    with pytest.raises(PlanError):
        plans.update_plan(db, p.id, {"colour": "red"})
    assert p.amount == 10.0  # a refused change leaves the plan as it was


def test_a_mistaken_plan_can_be_deleted(db):
    p = plan(db)
    plans.delete_plan(db, p.id)
    assert plans.list_plans(db, today=TODAY)["plans"] == []
    with pytest.raises(LookupError):
        plans.delete_plan(db, p.id)


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
    return TestClient(app)


BODY = {"broker": "N26", "instrument": "FTSE", "amount": 35, "frequency": "biweekly", "start_date": "2026-09-01"}


def test_the_api_creates_lists_changes_suspends_resumes_and_deletes(client):
    made = client.post("/investments/plans", json=BODY)
    assert made.status_code == 201 and made.json()["per_month"] == 75.83
    plan_id = made.json()["id"]
    assert client.get("/investments/plans").json()["summary"]["per_month"] == 75.83

    edited = client.patch(f"/investments/plans/{plan_id}", json={"anchor_date": "2026-09-08", "note": "app"})
    assert edited.json()["anchor_date"] == "2026-09-08" and edited.json()["note"] == "app"

    changed = client.post(f"/investments/plans/{plan_id}/change", json={"from_date": "2027-01-01", "amount": 40})
    assert changed.status_code == 200 and changed.json()["amount"] == 40.0 and changed.json()["status"] == "scheduled"

    stopped = client.post(f"/investments/plans/{plan_id}/suspend", json={"on": "2026-12-01"})
    assert stopped.json()["end_date"] == "2026-11-30"
    resumed = client.post(f"/investments/plans/{plan_id}/resume", json={"on": "2026-12-20"})
    assert resumed.status_code == 200 and resumed.json()["id"] != plan_id

    assert client.delete(f"/investments/plans/{plan_id}").status_code == 204
    assert client.delete(f"/investments/plans/{plan_id}").status_code == 404


def test_the_api_explains_refusals(client):
    assert client.post("/investments/plans", json={**BODY, "amount": 0}).status_code == 400
    assert client.post("/investments/plans", json={**BODY, "broker": "Nope"}).status_code == 400
    assert client.post("/investments/plans", json={**BODY, "start_date": "not-a-date"}).status_code == 422
    plan_id = client.post("/investments/plans", json=BODY).json()["id"]
    assert client.patch(f"/investments/plans/{plan_id}", json={"start_date": "31/12/2026"}).status_code == 400
    assert client.patch("/investments/plans/999", json={"note": "x"}).status_code == 404
    assert client.post(f"/investments/plans/{plan_id}/resume", json={}).status_code == 400  # it is not suspended
    assert client.post("/investments/plans/999/suspend", json={}).status_code == 404
