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
import datetime
import json
import pathlib
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from config import settings
from database.migrate import ensure_schema_current
from database.models import DBBankStatement, DBBankTransaction, DBReceipt, DBReviewQuestion
from services.categories import prompt_block
from services.claude_runner import SRC_DIR, ClaudeRun, run_claude
from services.file_hash import source_files, source_sha256
from services.linking import auto_mirror_paypal, auto_pair_transfers, mirrored_ids
from services.statement_store import MONTH_ABBR

PROMPTS = SRC_DIR / "prompts"
INBOX, FAILED, DUPLICATES = "_inbox", "_failed", "_duplicates"

AUTO, RECEIPT, STATEMENT = "auto", "receipt", "statement"

RECEIPT_TOOLS = ["mcp__fire__save_receipt", "mcp__fire__find_transactions", "mcp__fire__link_receipts"]
STATEMENT_TOOLS = [
    "mcp__fire__save_statement",
    "mcp__fire__find_receipts",
    "mcp__fire__find_transactions",
    "mcp__fire__link_receipts",
    "mcp__fire__link_transfers",
    "mcp__fire__link_payment_details",
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


def rules_text(kind: str, db: Session) -> str:
    """System prompt for a run. `auto` = router + both rule sets; Claude picks the section."""
    receipt = (PROMPTS / "receipt_rules.md").read_text(encoding="utf-8")
    statement = (PROMPTS / "statement_rules.md").read_text(encoding="utf-8")
    categories = prompt_block(db)  # the household's current list, rebuilt for every run
    if kind == RECEIPT:
        return f"{receipt}\n\n{categories}"
    if kind == STATEMENT:
        return f"{statement}\n\n{categories}"
    router = (PROMPTS / "router_rules.md").read_text(encoding="utf-8")
    return (
        f"{router}\n\n# RECEIPT RULES (only if the document is a receipt)\n\n{receipt}\n\n"
        f"# STATEMENT RULES (only if the document is a bank statement)\n\n{statement}\n\n"
        f"{categories}"
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


def move_back_to_inbox(src: pathlib.Path, owner: str) -> pathlib.Path:
    """Put a document that failed (or never ran) back into the owner's inbox to be processed again."""
    check_owner(owner)
    if src.parent == inbox_dir(owner):
        return src  # never left the inbox (e.g. the job failed before Claude ran)
    dest = _move(src, inbox_dir(owner))
    error_note = src.with_name(src.name + ".error.txt")
    if error_note.exists():
        error_note.unlink()
    return dest


def _run_claude(
    kind: str, owner: str, doc: pathlib.Path, result_file: pathlib.Path, db: Session, hint: str | None = None
) -> ClaudeRun:
    spec = KINDS[kind]
    files = source_files(doc)
    return run_claude(
        system_prompt=rules_text(kind, db),
        prompt=(
            f"Today's date is {datetime.date.today().isoformat()}.\n"
            + (f"The uploader says this document is from: {hint}. Use exactly that as the bank.\n" if hint else "")
            + "Process this document. Files, in order:\n" + "\n".join(f"- {f}" for f in files)
        ),
        tools=spec["tools"],
        mcp_env={
            "FIRE_OWNER": owner,
            "FIRE_SOURCE_FILE": str(doc),
            "FIRE_RESULT_FILE": str(result_file),
        },
        cwd=doc if doc.is_dir() else doc.parent,  # Claude can only read from the inbox
        timeout=spec["timeout"](),
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
    own_ids = {r.id for r in rows}
    paypal = sum(1 for r in rows if r.mirror_of is not None) + len(own_ids & mirrored_ids(db))
    return (
        f" Linked {receipts} receipt(s), {transfers} transfer side(s) and {paypal} PayPal payment(s); "
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


def ingest_document(
    kind: str, owner: str, doc: pathlib.Path, db: Session, hint: str | None = None
) -> IngestResult:
    """Read `doc` (file or folder of files) with Claude and file it. `kind` is normally auto."""
    check_owner(owner)
    ensure_schema_current(db)  # an out-of-date database must not cost a Claude run
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
    outcome = None
    try:
        run = _run_claude(kind, owner, doc, result_file, db, hint)
    finally:
        if result_file.exists():
            outcome = json.loads(result_file.read_text(encoding="utf-8"))
        shutil.rmtree(tmp, ignore_errors=True)
    cost, turns, error_detail = run.cost_usd, run.turns, run.error_detail

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
        auto_pair_transfers(db)  # cheap deterministic passes for pairs Claude did not link
        auto_mirror_paypal(db)
        extra = _link_summary_statement(db, record)

    dest = _move(doc, folder)
    record.source_path = str(dest)
    db.commit()
    status = "saved" if record.status == "ok" else "needs_review"
    # The tool reply for statements ends with a transaction listing meant for Claude only.
    summary = outcome["message"].split("\nStored transactions:")[0].strip()
    if status == "needs_review" and record.review_note:
        extra += f" Please check: {record.review_note[:300]}"
    return IngestResult(
        status, summary + extra, receipt_id=stored_id, filed_path=dest, kind=detected, **common
    )
