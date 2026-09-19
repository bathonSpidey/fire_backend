"""Ingest one receipt file: run headless Claude Code with the save_receipt tool, then file it.

Flow:  workspace/_inbox/<Owner>/<file>  --claude reads + calls save_receipt-->  DB row
       --purchase_date is now known-->  workspace/<Owner>/<Month_Year>/<file>

Claude runs on the logged-in Claude Code subscription of this machine, with the default coding
agent prompt replaced by prompts/receipt_rules.md and only the Read tool + save_receipt enabled.
"""

import calendar
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from config import settings
from database.models import DBReceipt

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
MCP_SERVER = SRC_DIR / "mcp_server" / "fire_mcp.py"
RULES_FILE = SRC_DIR / "prompts" / "receipt_rules.md"
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
INBOX, FAILED, DUPLICATES = "_inbox", "_failed", "_duplicates"


@dataclass
class IngestResult:
    status: str  # saved | needs_review | duplicate | failed
    message: str
    receipt_id: int | None = None
    filed_path: pathlib.Path | None = None
    cost_usd: float | None = None
    turns: int | None = None
    seconds: float = 0.0


def inbox_dir(owner: str) -> pathlib.Path:
    return settings.FIRE_WORKSPACE_ROOT / INBOX / owner


def month_folder(owner: str, purchase_date) -> pathlib.Path:
    label = f"{calendar.month_name[purchase_date.month]}_{purchase_date.year}"
    return settings.FIRE_WORKSPACE_ROOT / owner / label


def check_owner(owner: str) -> str:
    # The owner becomes a folder name, so only configured household members are accepted.
    if owner not in settings.FIRE_OWNERS:
        raise ValueError(f"Unknown owner '{owner}'. Expected one of {settings.FIRE_OWNERS}.")
    return owner


def save_to_inbox(owner: str, filename: str, data: bytes) -> pathlib.Path:
    """Store an uploaded file in the owner's inbox under a safe, unique name."""
    check_owner(owner)
    suffix = pathlib.Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{suffix}'.")
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in pathlib.Path(filename).stem)
    target_dir = inbox_dir(owner)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{stem}{suffix}"
    if target.exists():
        target = target_dir / f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
    target.write_bytes(data)
    return target


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _move(src: pathlib.Path, dest_dir: pathlib.Path) -> pathlib.Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}_{uuid.uuid4().hex[:6]}{dest.suffix}")
    shutil.move(str(src), str(dest))
    return dest


def _run_claude(owner: str, file: pathlib.Path, result_file: pathlib.Path, tmp: pathlib.Path):
    mcp_config = {
        "mcpServers": {
            "fire": {
                "command": sys.executable,
                "args": [str(MCP_SERVER)],
                "env": {
                    "PYTHONPATH": str(SRC_DIR),
                    "FIRE_DATABASE_URL": settings.FIRE_DATABASE_URL,
                    "FIRE_OWNER": owner,
                    "FIRE_SOURCE_FILE": str(file),
                    "FIRE_RESULT_FILE": str(result_file),
                    "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                },
            }
        }
    }
    config_path = tmp / "mcp.json"
    config_path.write_text(json.dumps(mcp_config), encoding="utf-8")

    cmd = [
        shutil.which("claude") or "claude",
        "-p",
        "--model", settings.CLAUDE_MODEL,
        "--effort", settings.CLAUDE_EFFORT,
        "--system-prompt", RULES_FILE.read_text(encoding="utf-8"),
        "--tools", "Read",
        "--allowedTools", "Read", "mcp__fire__save_receipt",
        "--strict-mcp-config", "--mcp-config", str(config_path),
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    env = os.environ.copy()
    # Never let a stray API key silently switch billing away from the logged-in subscription.
    env.pop("ANTHROPIC_API_KEY", None)

    return subprocess.run(
        cmd,
        input=f"Process this receipt file: {file}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=settings.CLAUDE_TIMEOUT_SECONDS,
        cwd=file.parent,  # Claude can only read from the inbox folder
        env=env,
    )


def ingest_receipt(owner: str, file: pathlib.Path, db: Session) -> IngestResult:
    check_owner(owner)
    started = time.monotonic()
    root = settings.FIRE_WORKSPACE_ROOT

    # Cheap exit before spending any tokens: this exact file was processed before.
    known = db.query(DBReceipt).filter(DBReceipt.file_hash == _sha256(file)).first()
    if known:
        _move(file, root / DUPLICATES / owner)
        return IngestResult(
            "duplicate",
            f"Same file already stored as receipt #{known.id}.",
            receipt_id=known.id,
            seconds=time.monotonic() - started,
        )

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fire_ingest_"))
    result_file = tmp / "result.json"
    cost = turns = None
    error_detail = ""
    outcome = None
    try:
        proc = _run_claude(owner, file, result_file, tmp)
        claude_text = proc.stdout
        try:
            payload = json.loads(proc.stdout)
            cost, turns = payload.get("total_cost_usd"), payload.get("num_turns")
            claude_text = str(payload.get("result", ""))
        except json.JSONDecodeError:
            pass
        error_detail = (proc.stderr or claude_text)[-2000:]
    except subprocess.TimeoutExpired:
        error_detail = f"Timed out after {settings.CLAUDE_TIMEOUT_SECONDS}s"
    finally:
        if result_file.exists():
            outcome = json.loads(result_file.read_text(encoding="utf-8"))
        shutil.rmtree(tmp, ignore_errors=True)

    common = dict(cost_usd=cost, turns=turns, seconds=time.monotonic() - started)

    if not outcome or not outcome["ok"]:
        dest = _move(file, root / FAILED / owner)
        reason = (outcome or {}).get("message") or error_detail or "Claude did not save a receipt."
        dest.with_name(dest.name + ".error.txt").write_text(reason, encoding="utf-8")
        return IngestResult("failed", reason, filed_path=dest, **common)

    db.expire_all()
    receipt = db.get(DBReceipt, outcome["receipt_id"])

    if outcome["duplicate"]:  # same purchase already stored from another file (photo vs PDF)
        dest = _move(file, root / DUPLICATES / owner)
        return IngestResult(
            "duplicate", outcome["message"], receipt_id=receipt.id, filed_path=dest, **common
        )

    dest = _move(file, month_folder(owner, receipt.purchase_date))
    receipt.source_path = str(dest)
    db.commit()
    status = "saved" if receipt.status == "ok" else "needs_review"
    return IngestResult(
        status, outcome["message"], receipt_id=receipt.id, filed_path=dest, **common
    )
