import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database.models import Base, DBIngestJob
from database.session import get_db
from routes.receipt_ingest import router
from services import ingest_worker
from services.receipt_ingest import IngestResult


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FIRE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(settings, "FIRE_OWNERS", ["Abir", "Lena"])
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_db():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    queued: list[int] = []
    monkeypatch.setattr(ingest_worker, "enqueue", queued.append)
    return TestClient(app), factory, queued


def upload(client, owner="Abir", name="bon.pdf", data=b"%PDF fake"):
    return client.post(
        "/receipts/upload", data={"owner": owner}, files=[("files", (name, data, "application/pdf"))]
    )


def test_owners_are_listed(env):
    client, _, _ = env
    assert client.get("/receipts/owners").json() == ["Abir", "Lena"]


def test_upload_saves_file_to_inbox_and_queues_a_job(env, tmp_path):
    client, factory, queued = env
    body = upload(client).json()
    assert client_status_ok(body)
    job = body["jobs"][0]
    assert (job["status"], job["owner"], job["original_name"]) == ("queued", "Abir", "bon.pdf")
    assert queued == [job["id"]]
    assert (tmp_path / "_inbox" / "Abir" / "bon.pdf").read_bytes() == b"%PDF fake"


def client_status_ok(body):
    return "jobs" in body and not body["rejected"]


def test_unknown_owner_is_rejected(env):
    client, _, queued = env
    assert upload(client, owner="../evil").status_code == 400
    assert queued == []


def test_unsupported_file_type_is_reported_not_queued(env):
    client, _, queued = env
    body = upload(client, name="notes.txt").json()
    assert body["jobs"] == []
    assert "Unsupported" in body["rejected"][0]["reason"]
    assert queued == []


def test_two_files_with_same_name_do_not_overwrite_each_other(env, tmp_path):
    client, _, _ = env
    upload(client, data=b"one")
    upload(client, data=b"two")
    assert len(list((tmp_path / "_inbox" / "Abir").iterdir())) == 2


def test_worker_records_result_on_job(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]

    def fake_ingest(owner, file, db):
        assert owner == "Abir" and file.exists()
        return IngestResult(
            "saved", "Saved as receipt #7", receipt_id=7, filed_path=pathlib.Path("x"), cost_usd=0.09
        )

    ingest_worker.process_job(job_id, factory, fake_ingest)
    job = client.get("/receipts/jobs").json()[0]
    assert (job["status"], job["receipt_id"], job["cost_usd"]) == ("saved", 7, 0.09)
    assert job["finished_at"]


def test_worker_survives_a_crashing_extractor(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]

    def boom(owner, file, db):
        raise RuntimeError("claude not found")

    ingest_worker.process_job(job_id, factory, boom)
    job = client.get("/receipts/jobs").json()[0]
    assert job["status"] == "failed" and "claude not found" in job["message"]


def test_worker_fails_job_whose_file_disappeared(env, tmp_path):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]
    (tmp_path / "_inbox" / "Abir" / "bon.pdf").unlink()
    ingest_worker.process_job(job_id, factory, lambda *a: pytest.fail("must not run"))
    assert client.get("/receipts/jobs").json()[0]["status"] == "failed"


def test_finished_jobs_are_not_processed_twice(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]
    calls = []

    def once(owner, file, db):
        calls.append(1)
        return IngestResult("saved", "ok", receipt_id=1)

    ingest_worker.process_job(job_id, factory, once)
    ingest_worker.process_job(job_id, factory, once)
    assert len(calls) == 1
    with factory() as db:
        assert db.get(DBIngestJob, job_id).status == "saved"
