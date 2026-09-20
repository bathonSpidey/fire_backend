import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, DBInventoryItem, DBReceipt
from database.session import get_db
from routes import stock as stock_routes
from services import stock
from services.categories import seed_categories

D = datetime.date
TODAY = D(2026, 9, 20)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine):
    with sessionmaker(bind=engine)() as session:
        seed_categories(session)
        yield session


def add(db, name, key="groceries", storage="Kept Cool", qty=1, price=2.0, expiry=None, legacy="Food", **extra):
    receipt = DBReceipt(store_name="Kaufland", purchase_date=TODAY - datetime.timedelta(days=2),
                        total_amount=price * qty, owner="Abir", status="ok")
    db.add(receipt)
    db.flush()
    item = DBInventoryItem(receipt_id=receipt.id, name=name, quantity=qty, unit_cost=price, discount=0.0,
                           category=legacy, storage_condition=storage, date_purchased=receipt.purchase_date,
                           date_expiry=expiry, spend_category=key, **extra)
    db.add(item)
    db.commit()
    return item


def days(n):
    return TODAY + datetime.timedelta(days=n)


def by_name(views):
    return {v["name"]: v for v in views}


# ── what is stock, and where it lives ─────────────────────────────────────────────────────────
def test_items_are_grouped_by_where_they_live(db):
    add(db, "Milk", storage="Kept Cool")
    add(db, "Peas", storage="Frozen")
    add(db, "Rice", storage="Normal")
    add(db, "Aspirin", key="pharmacy", storage="Normal", legacy="Medicine")
    add(db, "Batteries", key="electronics", storage="Normal", legacy="Electronics")
    add(db, "Old row", key=None, storage="Normal", legacy="Drinks")  # legacy item without a spend category
    groups = {n: v["group"] for n, v in by_name(stock.stock_items(db, TODAY)).items()}
    assert groups == {"Milk": "fridge", "Peas": "freezer", "Rice": "pantry", "Aspirin": "home",
                      "Batteries": "home", "Old row": "pantry"}


def test_meals_out_and_deposits_are_not_things_you_keep(db):
    add(db, "Meal at Gasthaus", key="eating_out", storage="Normal")
    add(db, "Pfandartikel", key="deposit", storage="Normal")
    add(db, "Pizza delivery", key="takeaway", storage="Normal")
    add(db, "Bread", storage="Normal")
    assert [v["name"] for v in stock.stock_items(db, TODAY)] == ["Bread"]


def test_the_most_urgent_comes_first_and_undated_items_last(db):
    add(db, "Fine", expiry=days(20))
    add(db, "Undated", storage="Normal", expiry=None)
    add(db, "Expired", expiry=days(-2))
    add(db, "Tomorrow", expiry=days(1))
    views = stock.stock_items(db, TODAY)
    assert [v["name"] for v in views] == ["Expired", "Tomorrow", "Fine", "Undated"]
    assert [v["urgency"] for v in views] == ["expired", "soon", "ok", "none"]
    assert views[0]["days_left"] == -2 and views[1]["days_left"] == 1


def test_urgency_bands():
    assert [stock.urgency_of(d) for d in (None, -1, 0, 3, 4, 7, 8)] == ["none", "expired", "soon", "soon", "week", "week", "ok"]


# ── opened packages go bad sooner ─────────────────────────────────────────────────────────────
def test_opening_shortens_the_life_to_the_once_opened_days(db):
    item = add(db, "Milk", expiry=days(10), days_once_opened=3)
    assert stock.open_item(db, item.id, TODAY)["effective_expiry"] == days(3).isoformat()
    assert stock.view_of(db, item.id, TODAY)["date_expiry"] == days(10).isoformat()  # the printed date is kept


def test_without_a_known_once_opened_life_a_sensible_default_applies(db):
    fridge = add(db, "Sauce", expiry=days(60))
    pantry = add(db, "Jam", storage="Normal", expiry=days(200))
    assert stock.open_item(db, fridge.id, TODAY)["days_left"] == 4
    assert stock.open_item(db, pantry.id, TODAY)["days_left"] == 14


def test_opening_never_extends_life_and_does_not_apply_to_non_food(db):
    soon = add(db, "Yoghurt", expiry=days(1), days_once_opened=5)
    assert stock.open_item(db, soon.id, TODAY)["days_left"] == 1  # already sooner than opened + 5
    cream = add(db, "Hand cream", key="personal_care", storage="Normal", legacy="Cosmetics", expiry=days(300))
    assert stock.open_item(db, cream.id, TODAY)["days_left"] == 300


def test_opening_twice_keeps_the_first_day(db):
    item = add(db, "Milk", expiry=days(10), days_once_opened=3)
    stock.open_item(db, item.id, D(2026, 9, 18))
    assert stock.open_item(db, item.id, TODAY)["opened_on"] == "2026-09-18"


# ── using things up ───────────────────────────────────────────────────────────────────────────
def test_using_some_leaves_the_rest_and_using_the_last_finishes_it(db):
    item = add(db, "Yoghurt", qty=4, price=1.0, expiry=days(5))
    first = stock.use_item(db, item.id, 1, TODAY)
    assert first["quantity_left"] == 3 and first["finished"] is False and first["value_left"] == 3.0
    stock.use_item(db, item.id, 2, TODAY)
    last = stock.use_item(db, item.id, 1, TODAY)
    assert last["finished"] is True and last["quantity_left"] == 0
    row = db.get(DBInventoryItem, item.id)
    assert (row.status, row.finished_on) == ("Consumed", TODAY)
    assert stock.stock_items(db, TODAY) == []  # gone from the shelf


def test_nothing_can_be_used_from_something_that_is_finished(db):
    item = add(db, "Yoghurt")
    stock.finish_item(db, item.id, TODAY)
    for action in (lambda: stock.use_item(db, item.id), lambda: stock.open_item(db, item.id), lambda: stock.freeze_item(db, item.id)):
        with pytest.raises(stock.StockError):
            action()
    with pytest.raises(LookupError):
        stock.use_item(db, 9999)


def test_a_discount_lowers_the_value_of_what_is_left(db):
    item = add(db, "Wraps", qty=2, price=1.49)
    item.discount = 0.60
    db.commit()
    assert stock.view_of(db, item.id, TODAY)["value_left"] == round(2 * 1.49 - 0.60, 2)


# ── throwing away is recorded, giving away is not waste ───────────────────────────────────────
def test_throwing_away_part_of_it_records_waste_and_the_rest_stays(db):
    item = add(db, "Milk", qty=4, price=1.0, expiry=days(-1))
    view = stock.discard_item(db, item.id, "expired", amount=2, today=TODAY)
    assert view["quantity_left"] == 2 and view["finished"] is False
    row = db.get(DBInventoryItem, item.id)
    assert (row.wasted_quantity, row.wasted_on, row.waste_reason, row.status) == (2, TODAY, "expired", "Available")
    stock.use_item(db, item.id, 2, TODAY)  # the rest is drunk
    assert db.get(DBInventoryItem, item.id).status == "Spoiled"  # partly wasted: it is reported as such


def test_throwing_away_everything_finishes_it_as_spoiled_or_discarded(db):
    a, b = add(db, "Salad"), add(db, "Sauce")
    assert stock.discard_item(db, a.id, "spoiled", today=TODAY)["finished"] is True
    stock.discard_item(db, b.id, "disliked", today=TODAY)
    assert (db.get(DBInventoryItem, a.id).status, db.get(DBInventoryItem, b.id).status) == ("Spoiled", "Discarded")


def test_giving_something_away_is_not_waste(db):
    item = add(db, "Pasta sauce", storage="Normal", qty=2)
    stock.discard_item(db, item.id, "gave_away", today=TODAY)
    row = db.get(DBInventoryItem, item.id)
    assert (row.status, row.wasted_quantity, row.wasted_on) == ("Consumed", 0.0, None)
    assert stock.insights(db, 90, TODAY)["wasted_items"] == 0


def test_an_unknown_reason_is_refused(db):
    item = add(db, "Salad")
    with pytest.raises(stock.StockError):
        stock.discard_item(db, item.id, "because")


# ── freezing ────────────────────────────────────────────────────────────────────────────────────
def test_freezing_moves_it_to_the_freezer_with_a_long_life(db):
    item = add(db, "Chicken", expiry=days(1), location="Fridge top shelf")
    view = stock.freeze_item(db, item.id, TODAY)
    assert view["group"] == "freezer" and view["days_left"] == stock.FREEZER_DAYS
    assert view["location"] is None and view["urgency"] == "ok"


def test_only_unfrozen_food_can_be_frozen(db):
    with pytest.raises(stock.StockError):
        stock.freeze_item(db, add(db, "Peas", storage="Frozen").id)
    with pytest.raises(stock.StockError):
        stock.freeze_item(db, add(db, "Shampoo", key="personal_care", storage="Normal", legacy="Cosmetics").id)


# ── location, date, rating ────────────────────────────────────────────────────────────────────
def test_where_it_is_kept_and_the_real_date_can_be_set(db):
    item = add(db, "Cheese", expiry=days(9))
    view = stock.update_item(db, item.id, {"location": "  Fridge door ", "date_expiry": days(2)}, TODAY)
    assert view["location"] == "Fridge door" and view["days_left"] == 2
    assert stock.update_item(db, item.id, {"location": "   "}, TODAY)["location"] is None


def test_rating_and_buy_again_work_also_after_it_is_finished(db):
    item = add(db, "Protein pudding")
    stock.finish_item(db, item.id, TODAY)
    view = stock.update_item(db, item.id, {"rating": 5, "would_rebuy": True}, TODAY)
    assert (view["rating"], view["would_rebuy"]) == (5, True)
    with pytest.raises(stock.StockError):
        stock.update_item(db, item.id, {"rating": 6})


# ── the zero-waste picture ────────────────────────────────────────────────────────────────────
def test_score_reflects_what_was_used_against_what_was_thrown_away(db):
    used = add(db, "Cheese", price=10.0, expiry=days(30))
    wasted = add(db, "Salad", price=5.0, expiry=days(-1))
    stock.finish_item(db, used.id, TODAY)
    stock.discard_item(db, wasted.id, "expired", today=TODAY)
    result = stock.insights(db, 90, TODAY)
    assert (result["wasted_value"], result["used_value"]) == (5.0, 10.0)
    assert result["waste_rate_pct"] == 33.3 and result["score"] == 67
    assert result["by_reason"] == {"expired": 5.0} and result["days_since_last_waste"] == 0


def test_no_history_means_no_score_yet(db):
    add(db, "Milk")
    result = stock.insights(db, 90, TODAY)
    assert result["score"] is None and result["waste_rate_pct"] is None and result["days_since_last_waste"] is None


def test_waste_outside_the_period_is_ignored(db):
    old = add(db, "Old salad", price=5.0)
    stock.discard_item(db, old.id, "expired", today=TODAY - datetime.timedelta(days=200))
    assert stock.insights(db, 90, TODAY)["wasted_value"] == 0.0
    assert stock.insights(db, 365, TODAY)["wasted_value"] == 5.0


def test_using_something_up_just_in_time_counts_as_rescued(db):
    saved = add(db, "Yoghurt", price=2.0, expiry=days(1))
    early = add(db, "Cheese", price=3.0, expiry=days(30))
    stock.finish_item(db, saved.id, TODAY)
    stock.finish_item(db, early.id, TODAY)
    assert stock.insights(db, 90, TODAY)["rescued"] == {"items": 1, "value": 2.0}


def test_repeat_waste_is_flagged_by_name(db):
    for _ in range(2):
        salad = add(db, "Rocket Salad", price=2.0)
        stock.discard_item(db, salad.id, "expired", today=TODAY)
    add(db, "Steak", price=9.0)
    stock.discard_item(db, db.query(DBInventoryItem).filter_by(name="Steak").one().id, "spoiled", today=TODAY)
    result = stock.insights(db, 90, TODAY)
    assert result["repeat_waste"] == ["Rocket Salad"]
    assert [e["name"] for e in result["top_wasted"]] == ["Steak", "Rocket Salad"]


def test_buying_something_you_already_have_is_pointed_out(db):
    add(db, "Milk 1L", location="Fridge door")
    add(db, "milk 1l ")
    add(db, "Butter")
    dupes = stock.insights(db, 90, TODAY)["duplicates"]
    assert len(dupes) == 1 and dupes[0]["count"] == 2 and dupes[0]["total_left"] == 2


def test_favourites_and_things_to_avoid_come_from_ratings(db):
    love = add(db, "Protein pudding")
    meh = add(db, "Tuna Temptation")
    stock.update_item(db, love.id, {"rating": 5})
    stock.update_item(db, meh.id, {"rating": 1, "would_rebuy": False})
    result = stock.insights(db, 90, TODAY)
    assert [e["name"] for e in result["liked"]] == ["Protein pudding"]
    assert [e["name"] for e in result["avoid"]] == ["Tuna Temptation"]


def test_summary_counts_groups_value_and_what_is_at_risk(db):
    add(db, "Milk", qty=2, price=1.0, expiry=days(1))     # soon: 2.0 at risk
    add(db, "Peas", storage="Frozen", price=2.0, expiry=days(60))
    add(db, "Soap", key="personal_care", storage="Normal", legacy="Cosmetics", price=3.0)
    summary = stock.insights(db, 90, TODAY)["summary"]
    assert summary["items"] == 3 and summary["value"] == 7.0
    assert summary["groups"] == {"fridge": 1, "freezer": 1, "pantry": 0, "home": 1}
    assert summary["use_soon"] == 1 and summary["value_at_risk"] == 2.0


# ── what to cook ──────────────────────────────────────────────────────────────────────────────
def test_meal_prompt_lists_food_that_goes_off_soon_most_urgent_first(db):
    add(db, "Spinach", expiry=days(-1))
    add(db, "Milk", expiry=days(2), days_once_opened=3)
    add(db, "Rice", storage="Normal", expiry=days(300))
    add(db, "Aspirin", key="pharmacy", storage="Normal", legacy="Medicine", expiry=days(1))  # not food
    milk = db.query(DBInventoryItem).filter_by(name="Milk").one()
    stock.open_item(db, milk.id, TODAY)
    prompt = stock.meal_ideas_prompt(stock.stock_items(db, TODAY))
    assert prompt.index("Spinach") < prompt.index("Milk")
    assert "expired" in prompt and "opened" in prompt
    assert "Rice" not in prompt and "Aspirin" not in prompt


def test_no_meal_prompt_when_nothing_needs_using_up(db):
    add(db, "Rice", storage="Normal", expiry=days(300))
    assert stock.meal_ideas_prompt(stock.stock_items(db, TODAY)) is None


# ── HTTP ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(engine, db, monkeypatch):
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(stock_routes.router)
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_api_lists_stock_and_walks_an_item_through_its_life(client, db):
    item = add(db, "Yoghurt", qty=2, price=1.0, expiry=datetime.date.today() + datetime.timedelta(days=2))
    listing = client.get("/stock").json()
    assert [i["name"] for i in listing["items"]] == ["Yoghurt"] and listing["summary"]["use_soon"] == 1
    assert client.post(f"/stock/items/{item.id}/open").json()["opened_on"]
    assert client.patch(f"/stock/items/{item.id}", json={"location": "Fridge door", "rating": 4}).json()["location"] == "Fridge door"
    assert client.post(f"/stock/items/{item.id}/use", json={"amount": 1}).json()["finished"] is False
    last = client.post(f"/stock/items/{item.id}/use", json={"amount": 1}).json()
    assert last["finished"] is True and client.get("/stock").json()["items"] == []
    assert client.patch(f"/stock/items/{item.id}", json={"rating": 5, "would_rebuy": True}).json()["rating"] == 5


def test_api_refuses_bad_requests_with_a_reason(client, db):
    item = add(db, "Salad")
    assert client.post(f"/stock/items/{item.id}/discard", json={"reason": "because"}).status_code == 400
    assert client.post("/stock/items/9999/use", json={}).status_code == 404
    assert client.patch(f"/stock/items/{item.id}", json={"rating": 9}).status_code == 400
    assert client.post(f"/stock/items/{item.id}/freeze").status_code == 200
    assert client.post(f"/stock/items/{item.id}/freeze").status_code == 400
    assert client.get("/stock/insights?days=3").status_code == 422  # too short a period


def test_api_meal_ideas_only_calls_claude_when_something_needs_using_up(client, db, monkeypatch):
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="1. Spinach omelette", timed_out=False, error_detail="", cost_usd=0.02)

    monkeypatch.setattr(stock_routes, "run_claude", fake_run)
    add(db, "Rice", storage="Normal", expiry=datetime.date.today() + datetime.timedelta(days=300))
    quiet = client.post("/stock/meal-ideas").json()
    assert quiet["ideas"] is None and calls == []  # nothing to use up: no tokens spent
    add(db, "Spinach", expiry=datetime.date.today() + datetime.timedelta(days=1))
    busy = client.post("/stock/meal-ideas").json()
    assert busy["ideas"] == "1. Spinach omelette"
    assert "Spinach" in calls[0]["prompt"] and calls[0]["tools"] == [] and calls[0]["allow_read"] is False


# ── long-expired stock nobody tracked ─────────────────────────────────────────────────────────
def test_long_expired_items_are_stale_and_not_counted_as_use_first(db):
    add(db, "Old avocado", expiry=days(-40))
    add(db, "Yesterday milk", expiry=days(-1))
    views = by_name(stock.stock_items(db, TODAY))
    assert views["Old avocado"]["stale"] and not views["Yesterday milk"]["stale"]
    summary = stock.stock_summary(list(views.values()))
    assert (summary["use_soon"], summary["stale"]) == (1, 1)


def test_clearing_stale_stock_is_neither_waste_nor_use(db):
    old = add(db, "Old avocado", expiry=days(-40), price=3.0)
    add(db, "Yesterday milk", expiry=days(-1))
    assert stock.clear_stale(db, TODAY) == {"cleared": 1}
    db.refresh(old)
    assert old.status == "Consumed" and old.quantity_left == 0
    assert [v["name"] for v in stock.stock_items(db, TODAY)] == ["Yesterday milk"]
    result = stock.insights(db, 90, TODAY)
    assert (result["wasted_value"], result["used_value"], result["score"]) == (0, 0, None)
