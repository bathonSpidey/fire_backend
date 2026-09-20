import datetime
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database.models import (
    Base, DBBankStatement, DBBankTransaction, DBIngestJob, DBInventoryItem, DBReceipt, DBReviewQuestion,
)
from database.session import get_db
from models.statement import Bank, StatementLine, StatementSubmission, TxKind
from routes.documents import router
from services import ingest_worker, linking
from services.categories import seed_categories
from services.document_ingest import IngestResult
from services.receipt_store import delete_receipt
from services.statement_store import delete_statement, save_statement

D = datetime.date


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FIRE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(settings, "FIRE_OWNERS", ["Abir", "Lena"])
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        seed_categories(session)

    def override():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override
    queued = []
    monkeypatch.setattr(ingest_worker, "enqueue", queued.append)
    return TestClient(app), factory, queued, tmp_path


def line(day, amount, who, kind=TxKind.SPEND, category="groceries"):
    return StatementLine(booking_date=D(2026, 9, day), amount=amount, counterparty=who,
                         description=f"{who} {day}", kind=kind, category=category if kind in (TxKind.SPEND, TxKind.INCOME) else None)


def stored_statement(db, tmp_path, txs=None, bank=Bank.SPARKASSE, file_hash="s1", name="shot.png"):
    filed = tmp_path / "Abir" / "September_2026" / "statements"
    filed.mkdir(parents=True, exist_ok=True)
    source = filed / name
    source.write_bytes(b"png")
    txs = txs or [line(15, -30.0, "Vodafone"), line(19, -300.0, "N26", TxKind.INTERNAL_TRANSFER)]
    sub = StatementSubmission(bank=bank, period_start=D(2026, 9, 14), period_end=D(2026, 9, 20),
                              opening_balance=None, closing_balance=None, transactions=txs)
    out = save_statement(db, owner="Abir", source_path=str(source), file_hash=file_hash, sub=sub)
    assert out.ok
    return db.get(DBBankStatement, out.statement_id)


def stored_receipt(db, tmp_path, total=50.0, day=20, status="needs_review"):
    folder = tmp_path / "Abir" / "September_2026"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "bon.png"
    source.write_bytes(b"png")
    r = DBReceipt(store_name="Kaufland", purchase_date=D(2026, 9, day), total_amount=total, owner="Abir",
                  status=status, review_note="date not visible", source_path=str(source), file_hash="r1")
    db.add(r)
    db.flush()
    db.add(DBInventoryItem(receipt_id=r.id, name="Milk", quantity=1, unit_cost=total, discount=0.0, category="Food",
                           storage_condition="Kept Cool", date_purchased=r.purchase_date,
                           date_expiry=r.purchase_date + datetime.timedelta(days=7), spend_category="groceries"))
    db.commit()
    return r


def job_for(db, record, kind, status="needs_review"):
    job = DBIngestJob(owner="Abir", kind=kind, original_name="shot.png", inbox_path="gone", status=status,
                      receipt_id=record.id, filed_path=record.source_path, message="Saved FOR REVIEW")
    db.add(job)
    db.commit()
    return job


# ── the bank the uploader names ─────────────────────────────────────────────────────────────
def test_upload_accepts_a_known_bank_hint_and_rejects_others(env):
    client, factory, queued, _ = env
    files = [("files", ("shot.png", b"png", "image/png"))]
    ok = client.post("/documents/upload", data={"owner": "Abir", "bank_hint": "PayPal"}, files=files)
    assert ok.status_code == 202
    with factory() as db:
        assert db.get(DBIngestJob, ok.json()["jobs"][0]["id"]).hint == "PayPal"
    bad = client.post("/documents/upload", data={"owner": "Abir", "bank_hint": "Deutsche Bank"}, files=files)
    assert bad.status_code == 400 and "Unknown bank" in bad.json()["detail"]


def test_the_worker_passes_the_hint_to_the_reader_only_when_there_is_one(env):
    client, factory, _, _ = env
    files = [("files", ("shot.png", b"png", "image/png"))]
    with_hint = client.post("/documents/upload", data={"owner": "Abir", "bank_hint": "N26"}, files=files).json()["jobs"][0]["id"]
    without = client.post("/documents/upload", data={"owner": "Abir"}, files=files).json()["jobs"][0]["id"]
    seen = {}

    def fake(kind, owner, file, db, hint=None):
        seen[file.name] = hint
        return IngestResult("saved", "ok", receipt_id=1)

    ingest_worker.process_job(with_hint, factory, fake)
    ingest_worker.process_job(without, factory, fake)
    assert list(seen.values()).count("N26") == 1 and list(seen.values()).count(None) == 1


# ── read again ──────────────────────────────────────────────────────────────────────────────
def test_reread_a_statement_removes_it_cleanly_and_queues_a_new_job_with_the_bank(env):
    client, factory, queued, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path)
        receipt = stored_receipt(db, tmp_path, total=30.0)
        vodafone = db.query(DBBankTransaction).filter_by(counterparty="Vodafone").one()
        assert linking.link_receipt(db, vodafone.id, receipt.id, "likely", "maybe").ok  # opens a question
        assert db.query(DBReviewQuestion).count() == 1
        job = job_for(db, statement, "statement")
        job_id, source = job.id, pathlib.Path(statement.source_path)
    queued.clear()
    new = client.post(f"/documents/jobs/{job_id}/reread", json={"bank_hint": "PayPal"}).json()
    assert new["kind"] == "auto" and new["status"] == "queued" and queued == [new["id"]]
    with factory() as db:
        assert db.query(DBBankStatement).count() == 0 and db.query(DBBankTransaction).count() == 0
        assert db.query(DBReviewQuestion).count() == 0
        assert db.get(DBIngestJob, new["id"]).hint == "PayPal"
        assert f"Read again as job #{new['id']}" in db.get(DBIngestJob, job_id).message
    assert not source.exists() and (tmp_path / "_inbox" / "Abir" / "shot.png").exists()


def test_reread_a_statement_releases_linked_receipts_and_transfer_partners(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        stored_statement(db, tmp_path, bank=Bank.PAYPAL, file_hash="p", name="pp.png",
                                  txs=[line(19, 300.0, "Bank", TxKind.INTERNAL_TRANSFER)])
        sparkasse = stored_statement(db, tmp_path, file_hash="sp", name="sp.png",
                                     txs=[line(19, -300.0, "PayPal", TxKind.INTERNAL_TRANSFER), line(15, -30.0, "Vodafone")])
        out_tx = db.query(DBBankTransaction).filter_by(amount=-300.0).one()
        in_tx = db.query(DBBankTransaction).filter_by(amount=300.0).one()
        assert linking.link_transfer(db, out_tx.id, in_tx.id, "certain", "same amount").ok
        receipt = stored_receipt(db, tmp_path, total=30.0, status="ok")
        vodafone = db.query(DBBankTransaction).filter_by(counterparty="Vodafone").one()
        assert linking.link_receipt(db, vodafone.id, receipt.id, "certain", "ref").ok
        assert receipt.bank_statement_linked is True
        job_id = job_for(db, sparkasse, "statement").id
        receipt_id = receipt.id
    assert client.post(f"/documents/jobs/{job_id}/reread").status_code == 202
    with factory() as db:
        assert db.get(DBReceipt, receipt_id).bank_statement_linked is False  # its booking is gone
        partner = db.query(DBBankTransaction).filter_by(amount=300.0).one()
        assert partner.transfer_group is None and partner.link_status is None  # no longer paired


def test_reread_a_receipt_unlinks_its_bank_booking_and_refreshes_the_statement_copy(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path, txs=[line(15, -50.0, "Kaufland")])
        receipt = stored_receipt(db, tmp_path, total=50.0, status="ok")
        tx = db.query(DBBankTransaction).one()
        assert linking.link_receipt(db, tx.id, receipt.id, "certain", "ref").ok
        assert db.get(DBBankStatement, statement.id).transactions[0]["inventory_purchase_id"] == receipt.id
        job_id = job_for(db, receipt, "receipt", status="saved").id
        statement_id = statement.id
    assert client.post(f"/documents/jobs/{job_id}/reread").status_code == 202
    with factory() as db:
        assert db.query(DBReceipt).count() == 0 and db.query(DBInventoryItem).count() == 0
        tx = db.query(DBBankTransaction).one()
        assert (tx.receipt_id, tx.link_status) == (None, None)
        assert db.get(DBBankStatement, statement_id).transactions[0]["inventory_purchase_id"] is None


def test_reread_refuses_what_it_cannot_do_safely(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path)
        failed = DBIngestJob(owner="Abir", kind="statement", original_name="x", inbox_path="x", status="failed")
        db.add(failed)
        db.commit()
        good = job_for(db, statement, "statement")
        failed_id, good_id, source = failed.id, good.id, pathlib.Path(statement.source_path)
    assert client.post(f"/documents/jobs/{failed_id}/reread").status_code == 409  # not stored
    assert client.post("/documents/jobs/999/reread").status_code == 404
    assert client.post(f"/documents/jobs/{good_id}/reread", json={"bank_hint": "Nonsense"}).status_code == 400
    source.unlink()  # the original file vanished: nothing may be deleted then
    assert "no longer available" in client.post(f"/documents/jobs/{good_id}/reread").json()["detail"]
    with factory() as db:
        assert db.query(DBBankStatement).count() == 1


def test_a_statement_cannot_be_read_again_twice(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        job_id = job_for(db, stored_statement(db, tmp_path), "statement").id
    assert client.post(f"/documents/jobs/{job_id}/reread").status_code == 202
    assert client.post(f"/documents/jobs/{job_id}/reread").status_code == 409


# ── confirm ─────────────────────────────────────────────────────────────────────────────────
def test_confirming_a_receipt_can_correct_its_date_and_moves_the_expiry_with_it(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        receipt = stored_receipt(db, tmp_path, day=20)
        job_id, receipt_id = job_for(db, receipt, "receipt").id, receipt.id
    done = client.post(f"/documents/jobs/{job_id}/confirm", json={"purchase_date": "2026-09-14"}).json()
    assert done["status"] == "saved" and "[Checked]" in done["message"]
    with factory() as db:
        r = db.get(DBReceipt, receipt_id)
        assert (r.purchase_date, r.status) == (D(2026, 9, 14), "ok")
        item = db.query(DBInventoryItem).one()
        assert (item.date_purchased, item.date_expiry) == (D(2026, 9, 14), D(2026, 9, 21))  # still 7 days


def test_confirming_without_a_date_only_clears_the_flag(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        receipt = stored_receipt(db, tmp_path)
        job_id, receipt_id = job_for(db, receipt, "receipt").id, receipt.id
    assert client.post(f"/documents/jobs/{job_id}/confirm").status_code == 200
    with factory() as db:
        assert db.get(DBReceipt, receipt_id).purchase_date == D(2026, 9, 20)
        assert db.get(DBReceipt, receipt_id).status == "ok"


def test_confirming_a_partial_statement_keeps_the_note_that_it_has_no_balances(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path)
        assert "No opening/closing balance" in statement.review_note
        job_id, statement_id = job_for(db, statement, "statement").id, statement.id
    assert client.post(f"/documents/jobs/{job_id}/confirm").status_code == 200
    with factory() as db:
        st = db.get(DBBankStatement, statement_id)
        assert st.status == "ok" and "No opening/closing balance" in st.review_note


def test_a_review_note_from_claude_flags_a_statement_even_when_all_checks_pass(env):
    _, factory, _, tmp_path = env
    with factory() as db:
        sub = StatementSubmission(bank=Bank.PAYPAL, period_start=D(2026, 9, 1), period_end=D(2026, 9, 30),
                                  opening_balance=0.0, closing_balance=-30.0, transactions=[line(15, -30.0, "Vodafone")])
        out = save_statement(db, owner="Abir", source_path="s", file_hash="h", sub=sub,
                             review_note="bank not visible, assumed PayPal")
        st = db.get(DBBankStatement, out.statement_id)
        assert st.status == "needs_review" and st.review_note == "bank not visible, assumed PayPal"


# ── the cleanup helpers on their own ────────────────────────────────────────────────────────
def test_delete_receipt_and_statement_helpers_leave_no_dangling_references(env):
    _, factory, _, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path, txs=[line(15, -50.0, "Kaufland")])
        receipt = stored_receipt(db, tmp_path, total=50.0, status="ok")
        tx = db.query(DBBankTransaction).one()
        linking.link_receipt(db, tx.id, receipt.id, "certain", "ref")
        delete_receipt(db, receipt)
        assert db.query(DBBankTransaction).one().receipt_id is None
        delete_statement(db, statement)
        assert db.query(DBBankTransaction).count() == 0 and db.query(DBBankStatement).count() == 0


def test_a_merged_paypal_upload_cannot_be_read_again(env):
    client, factory, _, tmp_path = env
    with factory() as db:
        statement = stored_statement(db, tmp_path, bank=Bank.PAYPAL)
        job = job_for(db, statement, "statement", status="saved")
        job.message = "Merged into PayPal statement #1 (Sep 2026): 2 new transactions added, 3 already present."
        db.commit()
        job_id = job.id
    response = client.post(f"/documents/jobs/{job_id}/reread")
    assert response.status_code == 409 and "whole month" in response.json()["detail"]
    with factory() as db:
        assert db.query(DBBankStatement).count() == 1  # nothing was removed
