import json
import shutil
import subprocess
import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from services import auth

router = APIRouter(prefix="/auth", tags=["Auth"])
claude_router = APIRouter(prefix="/claude", tags=["Claude"])

_CLAUDE_CACHE: dict = {"at": 0.0, "value": None}
CLAUDE_CACHE_SECONDS = 30


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_login(request: Request) -> None:
    """Everything except signing in needs the PIN; with no PIN set, only this computer may use the app."""
    creds = auth.load()
    if creds is None:
        if _address(request) in auth.LOOPBACK:
            return
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No PIN is set yet. On the laptop run: uv run python scripts/set_pin.py",
        )
    if not auth.valid_token(request.cookies.get(auth.COOKIE), creds):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")


class LoginIn(BaseModel):
    pin: str


@router.get("/status")
def auth_status(request: Request) -> dict:
    creds = auth.load()
    if creds is None:
        return {"pin_set": False, "authenticated": _address(request) in auth.LOOPBACK}
    return {"pin_set": True, "authenticated": auth.valid_token(request.cookies.get(auth.COOKIE), creds)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    creds = auth.load()
    if creds is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No PIN is set yet. On the laptop run: uv run python scripts/set_pin.py")
    address = _address(request)
    locked = auth.seconds_locked(address)
    if locked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"Too many wrong PINs. Try again in {locked // 60 + 1} minutes."
        )
    if not auth.check_pin(body.pin, creds):
        auth.record_failure(address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That PIN is not right.")
    auth.record_success(address)
    response.set_cookie(
        auth.COOKIE, auth.make_token(creds), max_age=auth.SESSION_SECONDS, httponly=True, samesite="lax", path="/"
    )
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE, path="/")
    return {"authenticated": False}


def claude_login_state() -> dict:
    """Whether Claude Code on this laptop is signed in (free to ask, cached for a few seconds)."""
    if time.time() - _CLAUDE_CACHE["at"] < CLAUDE_CACHE_SECONDS and _CLAUDE_CACHE["value"]:
        return _CLAUDE_CACHE["value"]
    try:
        out = subprocess.run(
            [shutil.which("claude") or "claude", "auth", "status"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        value = {"logged_in": bool(json.loads(out.stdout).get("loggedIn")), "checked": True}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        value = {"logged_in": None, "checked": False}  # could not tell: do not alarm anybody
    _CLAUDE_CACHE.update(at=time.time(), value=value)
    return value


@claude_router.get("/status")
def claude_status() -> dict:
    return claude_login_state()
