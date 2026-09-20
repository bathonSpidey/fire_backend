import hashlib
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
from routes.documents import router
from services import ingest_worker
from services.document_ingest import IngestResult
from services.file_hash import source_files, source_sha256


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
        "/documents/upload", data={"owner": owner}, files=[("files", (name, data, "application/pdf"))]
    )


def test_owners_are_listed(env):
    client, _, _ = env
    assert client.get("/documents/owners").json() == ["Abir", "Lena"]


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

    def fake_ingest(kind, owner, file, db):
        assert kind == "auto" and owner == "Abir" and file.exists()
        return IngestResult(
            "saved", "Saved as receipt #7", receipt_id=7, filed_path=pathlib.Path("x"), cost_usd=0.09
        )

    ingest_worker.process_job(job_id, factory, fake_ingest)
    job = client.get("/documents/jobs").json()[0]
    assert (job["status"], job["receipt_id"], job["cost_usd"]) == ("saved", 7, 0.09)
    assert job["finished_at"]


def test_worker_survives_a_crashing_extractor(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]

    def boom(kind, owner, file, db):
        raise RuntimeError("claude not found")

    ingest_worker.process_job(job_id, factory, boom)
    job = client.get("/documents/jobs").json()[0]
    assert job["status"] == "failed" and "claude not found" in job["message"]


def test_worker_fails_job_whose_file_disappeared(env, tmp_path):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]
    (tmp_path / "_inbox" / "Abir" / "bon.pdf").unlink()
    ingest_worker.process_job(job_id, factory, lambda *a: pytest.fail("must not run"))
    assert client.get("/documents/jobs").json()[0]["status"] == "failed"


def test_finished_jobs_are_not_processed_twice(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]
    calls = []

    def once(kind, owner, file, db):
        calls.append(1)
        return IngestResult("saved", "ok", receipt_id=1)

    ingest_worker.process_job(job_id, factory, once)
    ingest_worker.process_job(job_id, factory, once)
    assert len(calls) == 1
    with factory() as db:
        assert db.get(DBIngestJob, job_id).status == "saved"


def upload_many(client, names, group, owner="Abir"):
    files = [("files", (n, f"bytes-of-{n}".encode(), "image/png")) for n in names]
    return client.post("/documents/upload", data={"owner": owner, "group": str(group).lower()}, files=files)


def test_default_upload_lets_claude_decide_the_kind(env):
    client, _, _ = env
    assert upload(client).json()["jobs"][0]["kind"] == "auto"


def test_without_group_every_file_is_its_own_document(env):
    client, _, queued = env
    body = upload_many(client, ["a.png", "b.png", "c.png"], group=False).json()
    assert len(body["jobs"]) == 3 and len(queued) == 3


def test_group_makes_one_job_with_numbered_files_in_upload_order(env, tmp_path):
    client, _, queued = env
    body = upload_many(client, ["shot_b.png", "shot_a.png", "shot_c.png"], group=True).json()
    assert len(body["jobs"]) == 1 and queued == [body["jobs"][0]["id"]]
    assert body["jobs"][0]["original_name"].startswith("3 files: shot_b.png")
    (folder,) = list((tmp_path / "_inbox" / "Abir").iterdir())
    assert folder.is_dir()
    assert [f.name for f in sorted(folder.iterdir())] == ["01_shot_b.png", "02_shot_a.png", "03_shot_c.png"]


def test_one_bad_file_rejects_the_whole_group(env, tmp_path):
    client, _, queued = env
    body = upload_many(client, ["a.png", "notes.txt"], group=True).json()
    assert body["jobs"] == [] and queued == []
    assert "Unsupported" in body["rejected"][0]["reason"]
    assert not (tmp_path / "_inbox").exists() or not any((tmp_path / "_inbox" / "Abir").iterdir())


def test_a_single_file_with_group_flag_is_just_a_file(env, tmp_path):
    client, _, _ = env
    body = upload_many(client, ["a.png"], group=True).json()
    assert body["jobs"][0]["original_name"] == "a.png"
    assert (tmp_path / "_inbox" / "Abir" / "a.png").is_file()


def test_worker_records_the_kind_claude_detected(env):
    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]
    ingest_worker.process_job(
        job_id, factory, lambda *a: IngestResult("saved", "ok", receipt_id=3, kind="statement")
    )
    assert client.get("/documents/jobs").json()[0]["kind"] == "statement"


def test_worker_can_process_a_folder_document(env):
    client, factory, _ = env
    job_id = upload_many(client, ["a.png", "b.png"], group=True).json()["jobs"][0]["id"]
    seen = []
    ingest_worker.process_job(
        job_id, factory, lambda kind, owner, doc, db: seen.append(doc.is_dir()) or IngestResult("saved", "ok")
    )
    assert seen == [True]


def test_single_file_hash_is_the_plain_sha256_so_old_hashes_stay_valid(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"hello")
    assert source_sha256(f) == hashlib.sha256(b"hello").hexdigest()


def test_group_hash_depends_on_content_and_order(tmp_path):
    def make(name, contents):
        d = tmp_path / name
        d.mkdir()
        for file_name, data in contents:
            (d / file_name).write_bytes(data)
        return d

    one = make("one", [("01_a.png", b"A"), ("02_b.png", b"B")])
    same = make("same", [("01_x.png", b"A"), ("02_y.png", b"B")])
    swapped = make("swapped", [("01_a.png", b"B"), ("02_b.png", b"A")])
    other = make("other", [("01_a.png", b"A"), ("02_b.png", b"C")])
    assert source_sha256(one) == source_sha256(same)  # names do not matter, bytes and order do
    assert len({source_sha256(one), source_sha256(swapped), source_sha256(other)}) == 3
    assert [f.name for f in source_files(one)] == ["01_a.png", "02_b.png"]


# ── an out-of-date database must not cost a Claude run ─────────────────────────────────────
def test_outdated_database_is_refused_before_anything_is_read(tmp_path, monkeypatch):
    from database.migrate import OutdatedDatabaseError, ensure_schema_current, upgrade_to_head
    from services import document_ingest

    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    monkeypatch.setattr(settings, "FIRE_DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.create_all(engine)  # tables exist but no migration history: behind the code
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(OutdatedDatabaseError) as err:
            ensure_schema_current(db)
        assert "Nothing was read" in str(err.value)
        called = []
        monkeypatch.setattr(document_ingest, "_run_claude", lambda *a, **k: called.append(1))
        doc = tmp_path / "bon.pdf"
        doc.write_bytes(b"x")
        monkeypatch.setattr(settings, "FIRE_OWNERS", ["Abir"])
        with pytest.raises(OutdatedDatabaseError):
            document_ingest.ingest_document("auto", "Abir", doc, db)
        assert called == []  # Claude was never started

    engine.dispose()
    current_url = f"sqlite:///{(tmp_path / 'new.db').as_posix()}"
    monkeypatch.setattr(settings, "FIRE_DATABASE_URL", current_url)
    upgrade_to_head()
    with sessionmaker(bind=create_engine(current_url))() as db:
        ensure_schema_current(db)  # up to date: no error


def test_worker_records_the_outdated_database_message_on_the_job(env):
    from database.migrate import OutdatedDatabaseError

    client, factory, _ = env
    job_id = upload(client).json()["jobs"][0]["id"]

    def refuse(kind, owner, file, db):
        raise OutdatedDatabaseError("Restart the backend. Nothing was read, so nothing was spent.")

    ingest_worker.process_job(job_id, factory, refuse)
    job = client.get("/documents/jobs").json()[0]
    assert job["status"] == "failed" and "Restart the backend" in job["message"]


# ── Try again ──────────────────────────────────────────────────────────────────────────────
def fail_job(client, factory):
    job_id = upload(client).json()["jobs"][0]["id"]
    ingest_worker.process_job(job_id, factory, lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    return job_id


def test_retry_queues_a_new_auto_job_for_the_same_file(env, tmp_path):
    client, factory, queued = env
    old_id = fail_job(client, factory)
    queued.clear()
    new = client.post(f"/documents/jobs/{old_id}/retry").json()
    assert new["kind"] == "auto" and new["status"] == "queued" and queued == [new["id"]]
    assert (tmp_path / "_inbox" / "Abir" / "bon.pdf").exists()
    jobs = {j["id"]: j for j in client.get("/documents/jobs").json()}
    assert f"Retried as job #{new['id']}" in jobs[old_id]["message"]


def test_retry_recovers_a_file_from_the_failed_folder_and_drops_its_error_note(env, tmp_path):
    client, factory, _ = env
    old_id = fail_job(client, factory)
    failed_dir = tmp_path / "_failed" / "Abir"
    failed_dir.mkdir(parents=True)
    moved = failed_dir / "bon.pdf"
    (tmp_path / "_inbox" / "Abir" / "bon.pdf").rename(moved)
    (failed_dir / "bon.pdf.error.txt").write_text("why it failed")
    with factory() as db:
        job = db.get(DBIngestJob, old_id)
        job.filed_path = str(moved)
        db.commit()
    new = client.post(f"/documents/jobs/{old_id}/retry").json()
    assert (tmp_path / "_inbox" / "Abir" / "bon.pdf").read_bytes() == b"%PDF fake"
    assert not moved.exists() and not (failed_dir / "bon.pdf.error.txt").exists()
    assert new["status"] == "queued"


def test_retry_rejects_jobs_that_cannot_or_should_not_be_retried(env, tmp_path):
    client, factory, _ = env
    assert client.post("/documents/jobs/999/retry").status_code == 404
    waiting = upload(client).json()["jobs"][0]["id"]
    assert client.post(f"/documents/jobs/{waiting}/retry").status_code == 409  # not failed

    old_id = fail_job(client, factory)
    assert client.post(f"/documents/jobs/{old_id}/retry").status_code == 202
    assert client.post(f"/documents/jobs/{old_id}/retry").status_code == 409  # already retried

    gone = fail_job(client, factory)
    for f in (tmp_path / "_inbox" / "Abir").iterdir():
        f.unlink()
    assert "no longer available" in client.post(f"/documents/jobs/{gone}/retry").json()["detail"]
