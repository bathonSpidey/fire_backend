"""Ingest one uploaded document with headless Claude Code.

A document is one file, or a folder of files that together form one document (several
screenshots of one bank statement, two photos of one long receipt). Claude decides whether it is
a receipt or a bank statement, stores it and links it to what is already known.

Flow:  workspace/_inbox/<Owner>/<file or folder>  --claude reads, saves, links-->  DB
       --the date/period is now known-->  workspace/<Owner>/<Month_Year>/[statements/]<file>

Claude runs on the logged-in Claude Code subscription of this machine, with the default coding
agent prompt replaced by the rules in prompts/*.md and only Read + this app's tools enabled.
"""

import calendar
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
from database.models import DBBankStatement, DBBankTransaction, DBReceipt, DBReviewQuestion
from services.file_hash import source_files, source_sha256
from services.linking import auto_pair_transfers
from services.statement_store import MONTH_ABBR

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
PROMPTS = SRC_DIR / "prompts"
MCP_SERVER = SRC_DIR / "mcp_server" / "fire_mcp.py"
INBOX, FAILED, DUPLICATES = "_inbox", "_failed", "_duplicates"

AUTO, RECEIPT, STATEMENT = "auto", "receipt", "statement"

RECEIPT_TOOLS = ["mcp__fire__save_receipt", "mcp__fire__find_transactions", "mcp__fire__link_receipts"]
STATEMENT_TOOLS = [
    "mcp__fire__save_statement",
    "mcp__fire__find_receipts",
    "mcp__fire__find_transactions",
    "mcp__fire__link_receipts",
    "mcp__fire__link_transfers",
]
RECEIPT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
STATEMENT_SUFFIXES = {".pdf", ".csv", ".png", ".jpg", ".jpeg"}  # screenshots/photos included

KINDS = {
    AUTO: {
        "suffixes": RECEIPT_SUFFIXES | STATEMENT_SUFFIXES,
        "tools": sorted(set(RECEIPT_TOOLS) | set(STATEMENT_TOOLS)),
        "timeout": lambda: settings.CLAUDE_STATEMENT_TIMEOUT_SECONDS,
    },
    RECEIPT: {
        "suffixes": RECEIPT_SUFFIXES,
        "tools": RECEIPT_TOOLS,
        "timeout": lambda: settings.CLAUDE_TIMEOUT_SECONDS,
    },
    STATEMENT: {
        "suffixes": STATEMENT_SUFFIXES,
        "tools": STATEMENT_TOOLS,
        "timeout": lambda: settings.CLAUDE_STATEMENT_TIMEOUT_SECONDS,
    },
}


def rules_text(kind: str) -> str:
    """System prompt for a run. `auto` = router + both rule sets; Claude picks the section."""
    receipt = (PROMPTS / "receipt_rules.md").read_text(encoding="utf-8")
    statement = (PROMPTS / "statement_rules.md").read_text(encoding="utf-8")
    if kind == RECEIPT:
        return receipt
    if kind == STATEMENT:
        return statement
    router = (PROMPTS / "router_rules.md").read_text(encoding="utf-8")
    return (
        f"{router}\n\n# RECEIPT RULES (only if the document is a receipt)\n\n{receipt}\n\n"
        f"# STATEMENT RULES (only if the document is a bank statement)\n\n{statement}"
    )


@dataclass
class IngestResult:
    status: str  # saved | needs_review | duplicate | failed
    message: str
    receipt_id: int | None = None  # for statements: the statement id
    filed_path: pathlib.Path | None = None
    cost_usd: float | None = None
    turns: int | None = None
    seconds: float = 0.0
    kind: str | None = None  # what Claude decided the document is: receipt | statement


def inbox_dir(owner: str) -> pathlib.Path:
    return settings.FIRE_WORKSPACE_ROOT / INBOX / owner


def month_folder(owner: str, year: int, month: int) -> pathlib.Path:
    return settings.FIRE_WORKSPACE_ROOT / owner / f"{calendar.month_name[month]}_{year}"


def check_owner(owner: str) -> str:
    # The owner becomes a folder name, so only configured household members are accepted.
    if owner not in settings.FIRE_OWNERS:
        raise ValueError(f"Unknown owner '{owner}'. Expected one of {settings.FIRE_OWNERS}.")
    return owner


def _safe_stem(filename: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in pathlib.Path(filename).stem)


def _check_suffix(filename: str, kind: str) -> str:
    suffix = pathlib.Path(filename).suffix.lower()
    if suffix not in KINDS[kind]["suffixes"]:
        hint = " Convert iPhone HEIC photos to JPG first." if suffix == ".heic" else ""
        raise ValueError(f"Unsupported file type '{suffix}'.{hint}")
    return suffix


def save_to_inbox(owner: str, filename: str, data: bytes, kind: str = AUTO) -> pathlib.Path:
    """Store one uploaded file in the owner's inbox under a safe, unique name."""
    check_owner(owner)
    suffix = _check_suffix(filename, kind)
    target_dir = inbox_dir(owner)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_stem(filename)}{suffix}"
    if target.exists():
        target = target_dir / f"{_safe_stem(filename)}_{uuid.uuid4().hex[:6]}{suffix}"
    target.write_bytes(data)
    return target


def save_group_to_inbox(
    owner: str, files: list[tuple[str, bytes]], kind: str = AUTO
) -> pathlib.Path:
    """Store several files as ONE document: a folder with 01_, 02_, ... in the given order."""
    check_owner(owner)
    for name, _ in files:
        _check_suffix(name, kind)
    folder = inbox_dir(owner) / f"group_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    for index, (name, data) in enumerate(files, start=1):
        suffix = pathlib.Path(name).suffix.lower()
        (folder / f"{index:02d}_{_safe_stem(name)}{suffix}").write_bytes(data)
    return folder


def _move(src: pathlib.Path, dest_dir: pathlib.Path) -> pathlib.Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}_{uuid.uuid4().hex[:6]}{dest.suffix}")
    shutil.move(str(src), str(dest))
    return dest


def _run_claude(kind: str, owner: str, doc: pathlib.Path, result_file: pathlib.Path, tmp: pathlib.Path):
    spec = KINDS[kind]
    mcp_config = {
        "mcpServers": {
            "fire": {
                "command": sys.executable,
                "args": [str(MCP_SERVER)],
                "env": {
                    "PYTHONPATH": str(SRC_DIR),
                    "FIRE_DATABASE_URL": settings.FIRE_DATABASE_URL,
                    "FIRE_OWNER": owner,
                    "FIRE_SOURCE_FILE": str(doc),
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
        "--system-prompt", rules_text(kind),
        "--tools", "Read",
        "--allowedTools", "Read", *spec["tools"],
        "--strict-mcp-config", "--mcp-config", str(config_path),
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    env = os.environ.copy()
    # Never let a stray API key silently switch billing away from the logged-in subscription.
    env.pop("ANTHROPIC_API_KEY", None)

    files = source_files(doc)
    prompt = "Process this document. Files, in order:\n" + "\n".join(f"- {f}" for f in files)
    return subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=spec["timeout"](),
        cwd=doc if doc.is_dir() else doc.parent,  # Claude can only read from the inbox
        env=env,
    )


def _link_summary_receipt(receipt: DBReceipt) -> str:
    return (
        " Matched to a bank booking."
        if receipt.bank_statement_linked
        else " Not on a bank statement yet."
    )


def _link_summary_statement(db: Session, statement: DBBankStatement) -> str:
    rows = db.query(DBBankTransaction).filter(DBBankTransaction.statement_id == statement.id).all()
    receipts = sum(1 for r in rows if r.receipt_id is not None)
    transfers = sum(1 for r in rows if r.transfer_group is not None)
    tx_ids = [r.id for r in rows]
    questions = (
        db.query(DBReviewQuestion)
        .filter(DBReviewQuestion.status == "open", DBReviewQuestion.transaction_id.in_(tx_ids))
        .count()
        if tx_ids
        else 0
    )
    return (
        f" Linked {receipts} receipt(s) and {transfers} transfer side(s); "
        f"{questions} question(s) for you."
    )


def _known_document(db: Session, digest: str):
    """A document stored earlier from identical file(s): (kind, row) or None."""
    receipt = db.query(DBReceipt).filter(DBReceipt.file_hash == digest).first()
    if receipt:
        return RECEIPT, receipt
    statement = db.query(DBBankStatement).filter(DBBankStatement.file_hash == digest).first()
    if statement:
        return STATEMENT, statement
    return None


def ingest_document(kind: str, owner: str, doc: pathlib.Path, db: Session) -> IngestResult:
    """Read `doc` (file or folder of files) with Claude and file it. `kind` is normally auto."""
    check_owner(owner)
    started = time.monotonic()
    root = settings.FIRE_WORKSPACE_ROOT

    # Cheap exit before spending any tokens: these exact files were processed before.
    known = _known_document(db, source_sha256(doc))
    if known:
        known_kind, row = known
        _move(doc, root / DUPLICATES / owner)
        return IngestResult(
            "duplicate",
            f"Same file(s) already stored ({known_kind} #{row.id}).",
            receipt_id=row.id,
            seconds=time.monotonic() - started,
            kind=known_kind,
        )

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fire_ingest_"))
    result_file = tmp / "result.json"
    cost = turns = None
    error_detail = ""
    outcome = None
    try:
        proc = _run_claude(kind, owner, doc, result_file, tmp)
        claude_text = proc.stdout
        try:
            payload = json.loads(proc.stdout)
            cost, turns = payload.get("total_cost_usd"), payload.get("num_turns")
            claude_text = str(payload.get("result", ""))
        except json.JSONDecodeError:
            pass
        error_detail = (proc.stderr or claude_text)[-2000:]
    except subprocess.TimeoutExpired:
        error_detail = f"Timed out after {KINDS[kind]['timeout']()}s"
    finally:
        if result_file.exists():
            outcome = json.loads(result_file.read_text(encoding="utf-8"))
        shutil.rmtree(tmp, ignore_errors=True)

    common = dict(cost_usd=cost, turns=turns, seconds=time.monotonic() - started)

    if not outcome or not outcome["ok"]:
        dest = _move(doc, root / FAILED / owner)
        # No save tool called usually means "not a receipt or statement": Claude says what it is.
        reason = (outcome or {}).get("message") or error_detail or "Claude did not save anything."
        dest.with_name(dest.name + ".error.txt").write_text(reason, encoding="utf-8")
        return IngestResult("failed", reason, filed_path=dest, **common)

    detected = outcome["kind"]
    table = DBReceipt if detected == RECEIPT else DBBankStatement
    stored_id = outcome["receipt_id"] if detected == RECEIPT else outcome["statement_id"]
    db.expire_all()
    record = db.get(table, stored_id)

    if outcome["duplicate"]:  # same content stored earlier from other file(s)
        dest = _move(doc, root / DUPLICATES / owner)
        return IngestResult(
            "duplicate", outcome["message"], receipt_id=stored_id, filed_path=dest, kind=detected, **common
        )

    if detected == RECEIPT:
        folder = month_folder(owner, record.purchase_date.year, record.purchase_date.month)
        extra = _link_summary_receipt(record)
    else:
        month = MONTH_ABBR.index(record.month) + 1
        folder = month_folder(owner, record.year, month) / "statements"
        auto_pair_transfers(db)  # cheap deterministic pass for pairs Claude did not link
        extra = _link_summary_statement(db, record)

    dest = _move(doc, folder)
    record.source_path = str(dest)
    db.commit()
    status = "saved" if record.status == "ok" else "needs_review"
    # The tool reply for statements ends with a transaction listing meant for Claude only.
    summary = outcome["message"].split("\nStored transactions:")[0].strip()
    return IngestResult(
        status, summary + extra, receipt_id=stored_id, filed_path=dest, kind=detected, **common
    )
