"""One household PIN in front of everything, so the app can be opened from a phone on the home network.

- The PIN is set on the laptop (scripts/set_pin.py) and kept only as a salted scrypt hash in a small
  file next to the database. Without a PIN the app answers to this computer only.
- Signing in gives a signed cookie (30 days, HttpOnly). Changing the PIN changes the signing secret,
  which signs everybody out.
- Wrong guesses are throttled per device address: five in a row lock that address for five minutes.
"""

import hashlib
import hmac
import json
import os
import pathlib
import secrets
import time
from dataclasses import dataclass

from config import settings

COOKIE = "fire_session"
SESSION_SECONDS = 30 * 24 * 3600
MIN_PIN_LENGTH = 6
MAX_FAILURES = 5
LOCK_SECONDS = 5 * 60
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


@dataclass
class Credentials:
    salt: bytes
    pin_hash: bytes
    secret: bytes


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, **_SCRYPT)


def _path() -> pathlib.Path:
    return pathlib.Path(settings.FIRE_AUTH_FILE)


def load() -> Credentials | None:
    """The stored PIN, or None while none has been set."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return Credentials(bytes.fromhex(data["salt"]), bytes.fromhex(data["hash"]), bytes.fromhex(data["secret"]))
    except (OSError, ValueError, KeyError):
        return None


def set_pin(pin: str) -> None:
    """Store a new PIN. A new secret signs every existing session out."""
    if len(pin) < MIN_PIN_LENGTH:
        raise ValueError(f"The PIN needs at least {MIN_PIN_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"salt": salt.hex(), "hash": _hash(pin, salt).hex(), "secret": secrets.token_hex(32)}),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)  # best effort; Windows ignores most of it
    except OSError:
        pass
    _failures.clear()


def check_pin(pin: str, creds: Credentials) -> bool:
    return hmac.compare_digest(_hash(pin, creds.salt), creds.pin_hash)


def make_token(creds: Credentials, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_SECONDS)
    body = f"{expires}.{secrets.token_hex(8)}"
    return f"{body}.{hmac.new(creds.secret, body.encode(), hashlib.sha256).hexdigest()}"


def valid_token(token: str | None, creds: Credentials, now: float | None = None) -> bool:
    try:
        expires, nonce, signature = (token or "").split(".")
        expected = hmac.new(creds.secret, f"{expires}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected) and int(expires) > (now or time.time())
    except ValueError:
        return False


# ── throttling wrong guesses ──────────────────────────────────────────────────────────────────
_failures: dict[str, tuple[int, float]] = {}  # address -> (wrong guesses in a row, locked until)


def seconds_locked(address: str, now: float | None = None) -> int:
    count, until = _failures.get(address, (0, 0.0))
    remaining = until - (now or time.time())
    return int(remaining) + 1 if remaining > 0 else 0


def record_failure(address: str, now: float | None = None) -> None:
    now = now or time.time()
    count, until = _failures.get(address, (0, 0.0))
    count = 1 if until and until < now else count + 1  # a served lock starts a fresh count
    _failures[address] = (count, now + LOCK_SECONDS if count >= MAX_FAILURES else 0.0)


def record_success(address: str) -> None:
    _failures.pop(address, None)
