import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from config import settings
from database.models import Base
from database.session import get_db
from services import auth, claude_runner
from services.categories import seed_categories

PHONE = ("192.168.1.50", 50000)
LAPTOP = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def pin_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FIRE_AUTH_FILE", tmp_path / "auth.json")
    auth._failures.clear()
    yield
    auth._failures.clear()


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        seed_categories(db)

    def override():
        with session_factory() as db:
            yield db

    main.app.dependency_overrides[get_db] = override
    yield session_factory
    main.app.dependency_overrides.clear()


def client(address=PHONE):
    return TestClient(main.app, client=address)


# ── nobody has set a PIN yet ──────────────────────────────────────────────────────────────────
def test_without_a_pin_only_this_computer_may_use_the_app(factory):
    assert client(LAPTOP).get("/api/categories").status_code == 200
    refused = client(PHONE).get("/api/categories")
    assert refused.status_code == 403 and "set_pin.py" in refused.json()["detail"]


def test_without_a_pin_signing_in_explains_what_to_do():
    res = client().post("/api/auth/login", json={"pin": "123456"})
    assert res.status_code == 409 and "set_pin.py" in res.json()["detail"]


# ── with a PIN ────────────────────────────────────────────────────────────────────────────────
def test_data_needs_the_pin_but_the_health_check_and_status_do_not(factory):
    auth.set_pin("482913")
    phone = client()
    assert phone.get("/api/categories").status_code == 401
    assert phone.get("/api/health").status_code == 200
    assert phone.get("/api/auth/status").json() == {"pin_set": True, "authenticated": False}
    assert client(LAPTOP).get("/api/categories").status_code == 401  # a set PIN applies to this computer too


def test_the_right_pin_opens_the_app_and_signing_out_closes_it_again(factory):
    auth.set_pin("482913")
    phone = client()
    assert phone.post("/api/auth/login", json={"pin": "000000"}).status_code == 401
    assert phone.get("/api/categories").status_code == 401

    res = phone.post("/api/auth/login", json={"pin": "482913"})
    assert res.status_code == 200
    assert "httponly" in res.headers["set-cookie"].lower()
    assert phone.get("/api/categories").status_code == 200
    assert phone.get("/api/auth/status").json()["authenticated"] is True

    phone.post("/api/auth/logout")
    assert phone.get("/api/categories").status_code == 401


def test_another_device_is_not_signed_in_by_someone_elses_cookie(factory):
    auth.set_pin("482913")
    phone = client()
    phone.post("/api/auth/login", json={"pin": "482913"})
    assert client().get("/api/categories").status_code == 401  # a fresh browser has no cookie


def test_changing_the_pin_signs_everyone_out(factory):
    auth.set_pin("482913")
    phone = client()
    phone.post("/api/auth/login", json={"pin": "482913"})
    assert phone.get("/api/categories").status_code == 200
    auth.set_pin("777777")
    assert phone.get("/api/categories").status_code == 401


def test_the_pin_is_not_stored_in_clear():
    auth.set_pin("482913")
    stored = settings.FIRE_AUTH_FILE.read_text(encoding="utf-8")
    assert "482913" not in stored and set(json.loads(stored)) == {"salt", "hash", "secret"}


def test_a_short_pin_is_refused():
    with pytest.raises(ValueError):
        auth.set_pin("1234")
    assert auth.load() is None


def test_five_wrong_pins_lock_that_device_even_for_the_right_pin(factory):
    auth.set_pin("482913")
    phone = client()
    for _ in range(auth.MAX_FAILURES):
        assert phone.post("/api/auth/login", json={"pin": "111111"}).status_code == 401
    locked = phone.post("/api/auth/login", json={"pin": "482913"})
    assert locked.status_code == 429 and "minutes" in locked.json()["detail"]
    # Another device is not affected.
    assert client(("192.168.1.77", 1)).post("/api/auth/login", json={"pin": "482913"}).status_code == 200


def test_the_lock_ends_after_five_minutes_and_a_good_login_clears_the_count():
    now = time.time()
    for _ in range(auth.MAX_FAILURES):
        auth.record_failure("a", now)
    assert auth.seconds_locked("a", now) > 0
    assert auth.seconds_locked("a", now + auth.LOCK_SECONDS + 1) == 0
    auth.record_failure("a", now + auth.LOCK_SECONDS + 2)  # a fresh count, not an instant relock
    assert auth.seconds_locked("a", now + auth.LOCK_SECONDS + 3) == 0
    auth.record_success("a")
    assert "a" not in auth._failures


def test_session_tokens_expire_and_cannot_be_forged():
    auth.set_pin("482913")
    creds = auth.load()
    now = time.time()
    token = auth.make_token(creds, now)
    assert auth.valid_token(token, creds, now + 60)
    assert not auth.valid_token(token, creds, now + auth.SESSION_SECONDS + 60)
    expires, nonce, signature = token.split(".")
    assert not auth.valid_token(f"{int(expires) + 999999}.{nonce}.{signature}", creds, now)
    assert not auth.valid_token("", creds, now) and not auth.valid_token(None, creds, now)
    assert not auth.valid_token("garbage", creds, now)


def test_unknown_api_paths_are_not_answered_with_the_web_page(factory):
    auth.set_pin("482913")
    phone = client()
    phone.post("/api/auth/login", json={"pin": "482913"})
    assert phone.get("/api/nothing-here").status_code == 404


# ── Claude signed out ─────────────────────────────────────────────────────────────────────────
def _claude_says(monkeypatch, payload):
    monkeypatch.setattr(
        claude_runner.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=1),
    )


def _run(tmp_path):
    return claude_runner.run_claude(
        system_prompt="s", prompt="p", tools=[], mcp_env={}, cwd=tmp_path, timeout=5, allow_read=False
    )


def test_a_signed_out_claude_is_reported_with_what_to_do(monkeypatch, tmp_path):
    _claude_says(monkeypatch, {"is_error": True, "result": "Not logged in · Please run /login"})
    run = _run(tmp_path)
    assert run.signed_out and run.text == ""
    assert "/login" in run.error_detail and "Try again" in run.error_detail


def test_an_expired_token_counts_as_signed_out_too(monkeypatch, tmp_path):
    _claude_says(monkeypatch, {"is_error": True, "result": "OAuth token has expired. Please run /login"})
    assert _run(tmp_path).signed_out


def test_other_errors_are_not_mistaken_for_a_signed_out_claude(monkeypatch, tmp_path):
    _claude_says(monkeypatch, {"is_error": True, "result": "Overloaded, please retry"})
    assert not _run(tmp_path).signed_out
    _claude_says(monkeypatch, {"is_error": False, "result": "You can log in to the shop with /login"})
    run = _run(tmp_path)
    assert not run.signed_out and "shop" in run.text  # a normal answer is never rewritten
