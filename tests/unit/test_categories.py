import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import (
    Base,
    DBBankStatement,
    DBBankTransaction,
    DBIngestJob,
    DBInventoryItem,
    DBReceipt,
)
from database.session import get_db
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from routes.categories import router
from services import categories as cat
from services import ingest_worker, recategorize
from services.document_ingest import IngestResult
from services.statement_store import save_statement

D = datetime.date


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine):
    with sessionmaker(bind=engine)() as session:
        cat.seed_categories(session)
        yield session


def add_item(db, name, key, store="Kaufland", amount=5.0, receipt=None):
    if receipt is None:
        receipt = DBReceipt(store_name=store, purchase_date=D(2026, 4, 3), total_amount=amount, status="ok")
        db.add(receipt)
        db.flush()
    item = DBInventoryItem(
        receipt_id=receipt.id, name=name, quantity=1, unit_cost=amount, discount=0.0, category="Food",
        storage_condition="Normal", date_purchased=D(2026, 4, 3), spend_category=key,
    )
    db.add(item)
    db.commit()
    return item


def add_statement(db):
    txs = [
        StatementLine(booking_date=D(2026, 4, 5), amount=-30.0, counterparty="Fressnapf",
                      description="Fressnapf Tiernahrung", kind=TxKind.SPEND, category="shopping_general"),
        StatementLine(booking_date=D(2026, 4, 6), amount=-9.0, counterparty="Bank", description="fee",
                      kind=TxKind.FEE),
        StatementLine(booking_date=D(2026, 4, 7), amount=-300.0, counterparty="Own", description="to n26",
                      kind=TxKind.INTERNAL_TRANSFER),
    ]
    sub = StatementSubmission(bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
                              opening_balance=0.0, closing_balance=-339.0, transactions=txs)
    assert save_statement(db, owner="Abir", source_path="s", file_hash="s", sub=sub).ok


# ── the list itself ──────────────────────────────────────────────────────────────────────
def test_seed_has_the_categories_the_household_asked_for(db):
    keys = set(cat.category_map(db))
    assert {"fuel", "ev_charging", "clothing", "groceries", "personal_care", "pharmacy", "eating_out"} <= keys
    assert cat.category_map(db)["salary"].flow == "income"


def test_prompt_block_lists_current_categories_and_reflects_edits(db):
    assert "- fuel - Fuel (petrol/diesel):" in cat.prompt_block(db)
    cat.update_category(db, "fuel", label="Petrol", description="Only petrol")
    cat.update_category(db, "taxi", active=False)
    block = cat.prompt_block(db)
    assert "- fuel - Petrol: Only petrol" in block
    assert "- taxi -" not in block  # inactive categories are not offered to Claude
    assert "(income)" in block


def test_create_slugifies_and_rejects_duplicates(db):
    new = cat.create_category(db, label="Cat food & treats", group_name="Shopping")
    assert new.key == "cat_food_treats" and new.flow == "expense"
    with pytest.raises(cat.CategoryError):
        cat.create_category(db, label="Cat food & treats", group_name="Shopping")
    with pytest.raises(cat.CategoryError):
        cat.create_category(db, label="Uncategorized", group_name="Other")


def test_a_categorys_type_cannot_be_flipped(db):
    with pytest.raises(cat.CategoryError):
        cat.update_category(db, "groceries", flow="income")


# ── merge / delete move the entries ───────────────────────────────────────────────────────
def test_merge_moves_items_and_transactions_and_removes_the_source(db):
    add_item(db, "Latte", "beverages")
    add_statement(db)
    db.query(DBBankTransaction).filter_by(counterparty="Fressnapf").one().category = "beverages"
    db.commit()
    moved = cat.merge_category(db, "beverages", "groceries")
    assert moved == (1, 1)
    item = db.query(DBInventoryItem).one()
    assert (item.spend_category, item.category) == ("groceries", "Food")
    assert db.query(DBBankTransaction).filter_by(counterparty="Fressnapf").one().category == "groceries"
    assert "beverages" not in cat.category_map(db, include_inactive=True)


def test_merge_refuses_mixing_income_and_expense(db):
    with pytest.raises(cat.CategoryError):
        cat.merge_category(db, "groceries", "salary")


def test_delete_leaves_entries_uncategorized_everywhere(db):
    add_item(db, "Latte", "beverages")
    add_statement(db)
    db.query(DBBankTransaction).filter_by(counterparty="Fressnapf").one().category = "beverages"
    db.commit()
    cat.delete_category(db, "beverages")
    assert db.query(DBInventoryItem).one().spend_category is None
    assert db.query(DBBankTransaction).filter_by(counterparty="Fressnapf").one().category is None


def test_usage_counts_include_uncategorized(db):
    add_item(db, "Mystery", None)
    add_item(db, "Milk", "groceries")
    usage = cat.usage_counts(db)
    assert usage[None].items == 1 and usage["groceries"].items == 1


# ── re-check plumbing (the Claude judgement itself is exercised live) ────────────────────
def test_collect_entries_filters_by_current_category_and_skips_transfers(db):
    add_item(db, "Tuna Temptation", "groceries")
    add_item(db, "Shampoo", "personal_care")
    add_item(db, "Mystery", None)
    add_statement(db)
    everything = recategorize.collect_entries(db, {})
    assert len(everything) == 5  # 3 items + 2 spending bookings; the transfer is not an entry
    only_groceries = recategorize.collect_entries(db, {"from_categories": ["groceries"], "include_uncategorized": False})
    assert [e.ref[0] for e in only_groceries] == ["i"] and "Tuna Temptation" in only_groceries[0].line
    with_uncat = recategorize.collect_entries(db, {"from_categories": ["groceries"]})
    assert {"Tuna Temptation", "Mystery"} <= {part.strip() for e in with_uncat for part in e.line.split("|")}


def test_collect_entries_respects_the_date_range(db):
    add_item(db, "April thing", "groceries")
    assert recategorize.collect_entries(db, {"date_from": "2026-05-01"}) == []
    assert len(recategorize.collect_entries(db, {"date_from": "2026-04-01", "date_to": "2026-04-30"})) == 1


def test_apply_changes_moves_entries_and_rejects_bad_proposals(db):
    cat.create_category(db, label="Pets", group_name="Shopping", key="pets2")
    item = add_item(db, "Tuna Temptation", "groceries")
    add_statement(db)
    fressnapf = db.query(DBBankTransaction).filter_by(counterparty="Fressnapf").one()
    transfer = db.query(DBBankTransaction).filter_by(kind="internal_transfer").one()
    applied, rejected = recategorize.apply_changes(db, [
        {"ref": f"i{item.id}", "category": "pets"},
        {"ref": f"t{fressnapf.id}", "category": "pets"},
        {"ref": f"t{transfer.id}", "category": "groceries"},   # transfers have no category
        {"ref": f"i{item.id}", "category": "salary"},           # income key on a purchase
        {"ref": "i99999", "category": "pets"},                  # no such entry
        {"ref": f"t{fressnapf.id}", "category": "made_up"},     # unknown key
        {"ref": "banana", "category": "pets"},
    ])
    assert applied == 2 and len(rejected) == 5
    db.refresh(item)
    assert item.spend_category == "pets" and item.category == "Other"
    db.refresh(fressnapf)
    assert fressnapf.category == "pets"
    statement = db.query(DBBankStatement).one()
    assert statement.transactions  # derived copy refreshed without error


# ── worker runs a re-check job without a file ────────────────────────────────────────────
def test_worker_runs_recheck_jobs_from_stored_parameters(engine, db):
    factory = sessionmaker(bind=engine)
    job = DBIngestJob(owner="household", kind="recategorize", original_name="Re-check",
                      inbox_path='{"from_categories": ["groceries"]}', status="queued")
    db.add(job)
    db.commit()
    seen = []
    ingest_worker.process_job(
        job.id, factory,
        ingest_fn=lambda *a: pytest.fail("uploads must not run"),
        recheck_fn=lambda params, session: seen.append(params) or IngestResult("saved", "Re-checked 3 entries", cost_usd=0.05),
    )
    with factory() as s:
        done = s.get(DBIngestJob, job.id)
        assert (done.status, done.message, done.cost_usd) == ("saved", "Re-checked 3 entries", 0.05)
    assert seen == [{"from_categories": ["groceries"]}]


# ── HTTP API ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(engine, db, monkeypatch):
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override
    queued = []
    monkeypatch.setattr(ingest_worker, "enqueue", queued.append)
    c = TestClient(app)
    c.queued = queued
    return c


def test_api_lists_creates_edits_merges_and_deletes(client, db):
    listing = client.get("/categories").json()
    assert any(c["key"] == "fuel" and c["group_name"] == "Transport" for c in listing)

    created = client.post("/categories", json={"label": "Cat food", "group_name": "Shopping"})
    assert created.status_code == 201 and created.json()["key"] == "cat_food"
    assert client.post("/categories", json={"label": "Cat food", "group_name": "Shopping"}).status_code == 400

    assert client.patch("/categories/cat_food", json={"label": "Cat supplies", "fixed": True}).json()["label"] == "Cat supplies"

    add_item(db, "Whiskas", "cat_food")
    merged = client.post("/categories/cat_food/merge", json={"into": "pets"}).json()
    assert merged == {"moved_items": 1, "moved_transactions": 0}
    assert client.post("/categories/pets/merge", json={"into": "pets"}).status_code == 400

    deleted = client.delete("/categories/pets").json()
    assert deleted["uncategorized_items"] == 1
    assert client.get("/categories/uncategorized").json()["items"] == 1
    assert client.delete("/categories/pets").status_code == 400


def test_api_recheck_counts_first_and_only_queues_real_work(client, db):
    add_item(db, "Tuna Temptation", "groceries")
    dry = client.post("/categories/recheck", json={"dry_run": True}).json()
    assert dry == {"entries": 1, "batches": 1, "job_id": None} and client.queued == []
    empty = client.post("/categories/recheck", json={"from_categories": ["fuel"], "include_uncategorized": False}).json()
    assert empty["job_id"] is None and client.queued == []
    real = client.post("/categories/recheck", json={"from_categories": ["groceries"]}).json()
    assert real["entries"] == 1 and client.queued == [real["job_id"]]
