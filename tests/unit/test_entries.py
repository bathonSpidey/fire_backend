import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, DBBankStatement, DBBankTransaction, DBInventoryItem, DBReceipt
from database.session import get_db
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from routes.entries import router
from services.categories import seed_categories
from services.statement_store import save_statement

D = datetime.date


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        seed_categories(db)
        txs = [
            StatementLine(booking_date=D(2026, 4, 5), amount=-30.0, counterparty="Amazon", description="Amazon 5",
                          kind=TxKind.SPEND, category="shopping_general"),
            StatementLine(booking_date=D(2026, 4, 24), amount=3000.0, counterparty="Employer", description="Salary",
                          kind=TxKind.INCOME, category="salary"),
            StatementLine(booking_date=D(2026, 4, 25), amount=-300.0, counterparty="Own", description="to n26",
                          kind=TxKind.INTERNAL_TRANSFER),
        ]
        sub = StatementSubmission(bank=Bank.SPARKASSE, period_start=D(2026, 4, 1), period_end=D(2026, 4, 30),
                                  opening_balance=0.0, closing_balance=2670.0, transactions=txs)
        assert save_statement(db, owner="Abir", source_path="s", file_hash="s", sub=sub).ok
        receipt = DBReceipt(store_name="Kaufland", purchase_date=D(2026, 4, 3), total_amount=5.0, status="ok")
        db.add(receipt)
        db.flush()
        db.add(DBInventoryItem(receipt_id=receipt.id, name="Tuna Temptation", quantity=1, unit_cost=5.0, discount=0.0,
                               category="Food", storage_condition="Normal", date_purchased=D(2026, 4, 3),
                               spend_category="groceries"))
        db.commit()

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override
    return TestClient(app), factory


def tx_id(factory, counterparty):
    with factory() as db:
        return db.query(DBBankTransaction).filter_by(counterparty=counterparty).one().id


def test_a_booking_can_be_moved_to_another_expense_category(env):
    client, factory = env
    tid = tx_id(factory, "Amazon")
    res = client.patch(f"/entries/transactions/{tid}", json={"category": "electronics"})
    assert res.status_code == 200 and res.json() == {"id": tid, "category": "electronics"}
    with factory() as db:
        assert db.get(DBBankTransaction, tid).category == "electronics"


def test_the_statements_page_data_carries_the_id_and_the_new_category(env):
    client, factory = env
    tid = tx_id(factory, "Amazon")
    client.patch(f"/entries/transactions/{tid}", json={"category": "electronics"})
    with factory() as db:
        entry = next(t for t in db.query(DBBankStatement).one().transactions if t["id"] == tid)
        assert entry["category"] == "electronics"


def test_income_and_expense_categories_cannot_be_swapped_by_hand(env):
    client, factory = env
    spend = client.patch(f"/entries/transactions/{tx_id(factory, 'Amazon')}", json={"category": "salary"})
    assert spend.status_code == 400 and "income category" in spend.json()["detail"] and "money out" in spend.json()["detail"]
    income = client.patch(f"/entries/transactions/{tx_id(factory, 'Employer')}", json={"category": "groceries"})
    assert income.status_code == 400 and "money in" in income.json()["detail"]
    ok = client.patch(f"/entries/transactions/{tx_id(factory, 'Employer')}", json={"category": "other_income"})
    assert ok.status_code == 200


def test_transfers_have_no_category_and_unknown_things_are_refused(env):
    client, factory = env
    transfer = client.patch(f"/entries/transactions/{tx_id(factory, 'Own')}", json={"category": "groceries"})
    assert transfer.status_code == 400 and "no category" in transfer.json()["detail"]
    unknown = client.patch(f"/entries/transactions/{tx_id(factory, 'Amazon')}", json={"category": "made_up"})
    assert unknown.status_code == 400 and "no active category" in unknown.json()["detail"]
    assert client.patch("/entries/transactions/9999", json={"category": "groceries"}).status_code == 404


def test_a_receipt_item_can_be_recategorised_and_its_pantry_group_follows(env):
    client, factory = env
    with factory() as db:
        item_id = db.query(DBInventoryItem).one().id
    res = client.patch(f"/entries/items/{item_id}", json={"category": "pets"})
    assert res.status_code == 200 and res.json()["category"] == "pets"
    with factory() as db:
        item = db.get(DBInventoryItem, item_id)
        assert (item.spend_category, item.category) == ("pets", "Other")
    assert client.patch(f"/entries/items/{item_id}", json={"category": "salary"}).status_code == 400
    assert client.patch("/entries/items/9999", json={"category": "pets"}).status_code == 404
