"""Re-check the category of existing entries with Claude after the category list changed.

Adding, splitting or renaming categories is deterministic for the entries that already carry the
old key (see services/categories.py). But "these should now be Pets" or "these uncategorized
entries need a home" is a judgement call, so Claude does it: it sees a compact list of entries,
and returns ONLY the ones whose category should change.
"""

import datetime
import json
import pathlib
import shutil
import tempfile
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import settings
from database.migrate import ensure_schema_current
from database.models import DBBankStatement, DBBankTransaction, DBInventoryItem, DBReceipt
from services.categories import category_map, legacy_item_category, prompt_block, validate_key
from services.claude_runner import SRC_DIR, run_claude
from services.document_ingest import IngestResult
from services.statement_store import sync_statement_json

BATCH_SIZE = 100
NOT_SPENDING_KINDS = ("internal_transfer", "investment")
INCOME_KINDS = ("income", "refund")
RULES_FILE = SRC_DIR / "prompts" / "recategorize_rules.md"


@dataclass
class Entry:
    ref: str  # "i123" = receipt item, "t45" = bank transaction
    line: str


def _category_filter(column, params: dict):
    keys = params.get("from_categories")
    if keys is None:
        return None
    conditions = [column.in_([k for k in keys if k])]
    if params.get("include_uncategorized", True) or None in keys:
        conditions.append(column.is_(None))
    return or_(*conditions)


def collect_entries(db: Session, params: dict) -> list[Entry]:
    date_from = datetime.date.fromisoformat(params["date_from"]) if params.get("date_from") else None
    date_to = datetime.date.fromisoformat(params["date_to"]) if params.get("date_to") else None
    entries: list[Entry] = []

    items = db.query(DBInventoryItem, DBReceipt).join(DBReceipt, DBReceipt.id == DBInventoryItem.receipt_id)
    condition = _category_filter(DBInventoryItem.spend_category, params)
    if condition is not None:
        items = items.filter(condition)
    if date_from:
        items = items.filter(DBReceipt.purchase_date >= date_from)
    if date_to:
        items = items.filter(DBReceipt.purchase_date <= date_to)
    for item, receipt in items.order_by(DBInventoryItem.id):
        amount = round((item.quantity or 1) * item.unit_cost - (item.discount or 0.0), 2)
        entries.append(Entry(
            f"i{item.id}",
            f"i{item.id} | {receipt.store_name} | {item.name} | {amount:.2f} | now={item.spend_category or 'none'}",
        ))

    txs = db.query(DBBankTransaction).filter(DBBankTransaction.kind.notin_(NOT_SPENDING_KINDS))
    condition = _category_filter(DBBankTransaction.category, params)
    if condition is not None:
        txs = txs.filter(condition)
    if date_from:
        txs = txs.filter(DBBankTransaction.booking_date >= date_from)
    if date_to:
        txs = txs.filter(DBBankTransaction.booking_date <= date_to)
    for tx in txs.order_by(DBBankTransaction.id):
        entries.append(Entry(
            f"t{tx.id}",
            f"t{tx.id} | {tx.counterparty} | {tx.description[:90]} | {tx.amount:+.2f} | kind={tx.kind} "
            f"| now={tx.category or 'none'}",
        ))
    return entries


def apply_changes(db: Session, changes: list[dict]) -> tuple[int, list[str]]:
    """Apply Claude's proposed category changes. Returns (applied, rejection messages)."""
    cats = category_map(db)
    applied, rejected = 0, []
    statement_ids: set[int] = set()
    for change in changes:
        ref, key = str(change.get("ref", "")), change.get("category")
        try:
            kind, row_id = ref[0], int(ref[1:])
        except (ValueError, IndexError):
            rejected.append(f"{ref}: not a valid entry reference")
            continue
        if kind == "i":
            row = db.get(DBInventoryItem, row_id)
            flow = "expense"
        elif kind == "t":
            row = db.get(DBBankTransaction, row_id)
            flow = "income" if row and (row.kind in INCOME_KINDS or row.amount > 0) else "expense"
            if row and row.kind in NOT_SPENDING_KINDS:
                rejected.append(f"{ref}: transfers and investments have no category")
                continue
        else:
            row = None
        if row is None:
            rejected.append(f"{ref}: no such entry")
            continue
        problem = validate_key(cats, key, flow)
        if problem:
            rejected.append(f"{ref}: {problem}")
            continue
        if kind == "i":
            row.spend_category, row.category = key, legacy_item_category(key)
        else:
            row.category = key
            statement_ids.add(row.statement_id)
        applied += 1
    db.flush()
    for statement in db.query(DBBankStatement).filter(DBBankStatement.id.in_(statement_ids)):
        sync_statement_json(db, statement)  # the Statements page reads this copy
    db.commit()
    return applied, rejected


def run(params: dict, db: Session) -> IngestResult:
    """Re-check the entries described by `params` in batches of BATCH_SIZE."""
    ensure_schema_current(db)
    entries = collect_entries(db, params)
    if not entries:
        return IngestResult("saved", "Nothing to re-check: no entries match.")

    system_prompt = f"{RULES_FILE.read_text(encoding='utf-8')}\n\n{prompt_block(db)}"
    total_cost, applied, failed_batches, notes = 0.0, 0, 0, []
    for start in range(0, len(entries), BATCH_SIZE):
        batch = entries[start:start + BATCH_SIZE]
        work = pathlib.Path(tempfile.mkdtemp(prefix="fire_recheck_"))
        result_file = work / "result.json"
        try:
            claude = run_claude(
                system_prompt=system_prompt,
                prompt="Re-check these entries (ref | source | text | amount | ...):\n"
                + "\n".join(e.line for e in batch),
                tools=["mcp__fire__apply_recategorization"],
                mcp_env={"FIRE_RESULT_FILE": str(result_file)},
                cwd=work,
                timeout=settings.CLAUDE_TIMEOUT_SECONDS,
                allow_read=False,
            )
            total_cost += claude.cost_usd or 0.0
            if result_file.exists():
                outcome = json.loads(result_file.read_text(encoding="utf-8"))
                applied += outcome["applied"]
                notes.extend(outcome["rejected"][:3])
            elif claude.timed_out or (claude.error_detail and not claude.text):
                failed_batches += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)

    batches = -(-len(entries) // BATCH_SIZE)
    message = f"Re-checked {len(entries)} entries: {applied} moved to a different category."
    if failed_batches:
        message += f" {failed_batches} of {batches} batches failed; run it again to finish."
    if notes:
        message += " Skipped: " + "; ".join(notes)
    status = "failed" if failed_batches == batches else "saved"
    return IngestResult(status, message, cost_usd=round(total_cost, 4))
