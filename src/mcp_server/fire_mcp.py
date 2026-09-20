"""MCP server handed to a headless `claude -p` run.

Who the document belongs to and which file is being processed are fixed by the launching
process via environment variables, so the model can neither pick an owner nor touch other files.
Which tools a run may use is restricted by the launcher (--allowedTools), per document kind.
NOTE: stdio transport -> never print to stdout in this process.
"""

import datetime
import json
import os
import pathlib
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from database.session import SessionLocal
from models.inventory import ReceiptSubmission
from models.statement import StatementSubmission
from services import linking, recategorize
from services.file_hash import source_sha256
from services.receipt_store import save_receipt as store_receipt
from services.statement_store import save_statement as store_statement

mcp = FastMCP("fire")


def _source() -> pathlib.Path:
    return pathlib.Path(os.environ["FIRE_SOURCE_FILE"])


def _file_sha256() -> str:
    return source_sha256(_source())


def _write_result(payload: dict) -> None:
    """Deterministic hand-off to the launching process (last call wins)."""
    pathlib.Path(os.environ["FIRE_RESULT_FILE"]).write_text(json.dumps(payload), encoding="utf-8")


@mcp.tool()
def save_receipt(receipt: ReceiptSubmission, review_note: str | None = None) -> str:
    """Store the receipt being processed. Call exactly once per file.

    The code verifies that the items add up to total_amount. If they don't, nothing is saved
    and you get a list of what to fix - correct it and call again.
    Only if you have re-read the receipt and it genuinely cannot be reconciled (illegible,
    cut off, missing lines), pass `review_note` explaining why; it is then saved flagged for
    human review instead of being rejected.
    """
    with SessionLocal() as db:
        outcome = store_receipt(
            db,
            owner=os.environ["FIRE_OWNER"],
            source_path=str(_source()),
            file_hash=_file_sha256(),
            sub=receipt,
            review_note=review_note,
        )
    _write_result(
        {
            "kind": "receipt",
            "ok": outcome.ok,
            "duplicate": outcome.duplicate,
            "receipt_id": outcome.receipt_id,
            "message": outcome.message,
        }
    )
    return outcome.message


@mcp.tool()
def save_statement(statement: StatementSubmission, review_note: str | None = None) -> str:
    """Store the statement being processed. Call exactly once per file.

    The code verifies opening balance + all bookings = closing balance. If not, nothing is
    saved and you get what to fix. Only if you have re-read the statement and it cannot be
    reconciled, pass `review_note`; it is then saved flagged for human review.
    On success you get the stored transactions with their ids, ready for linking.
    """
    with SessionLocal() as db:
        outcome = store_statement(
            db,
            owner=os.environ["FIRE_OWNER"],
            source_path=str(_source()),
            file_hash=_file_sha256(),
            sub=statement,
            review_note=review_note,
        )
    _write_result(
        {
            "kind": "statement",
            "ok": outcome.ok,
            "duplicate": outcome.duplicate,
            "statement_id": outcome.statement_id,
            "month_label": outcome.month_label,
            "message": outcome.message.splitlines()[0] if outcome.message else "",
        }
    )
    return outcome.message


@mcp.tool()
def find_receipts(
    date_from: datetime.date,
    date_to: datetime.date,
    only_unlinked: bool = True,
    amount: float | None = None,
) -> str:
    """List receipts (of the whole household) bought between two dates, oldest first.

    only_unlinked=True hides receipts already matched to a bank transaction. `amount` (euro,
    sign ignored) narrows to receipts with exactly that total.
    """
    with SessionLocal() as db:
        return json.dumps(linking.find_receipts(db, date_from, date_to, only_unlinked, amount))


@mcp.tool()
def find_transactions(
    date_from: datetime.date,
    date_to: datetime.date,
    only_unlinked: bool = True,
    amount: float | None = None,
    kind: str | None = "spend",
    bank: str | None = None,
    exclude_bank: str | None = None,
    unmirrored: bool = False,
) -> str:
    """List bank/PayPal transactions whose booking date OR purchase date is in the window.

    `amount` (euro, sign ignored) narrows to that exact amount. `kind` filters by
    spend|income|internal_transfer|investment|fee|cash|refund|other (null = all kinds).
    `bank` keeps one bank only (e.g. "PayPal"); `exclude_bank` drops one. `unmirrored`=true hides
    PayPal rows that already explain a bank booking and bank bookings already explained by one.
    """
    with SessionLocal() as db:
        return json.dumps(
            linking.find_transactions(
                db, date_from, date_to, only_unlinked, amount, kind, bank, exclude_bank, unmirrored
            )
        )


class ReceiptLink(BaseModel):
    transaction_id: int
    receipt_id: int
    confidence: Literal["certain", "likely"] = Field(
        description="certain = links immediately. likely = asks the household a yes/no question."
    )
    reason: str = Field(description="One short sentence: what makes you think they match")


class TransferLink(BaseModel):
    outgoing_transaction_id: int = Field(description="The negative side (money leaving)")
    incoming_transaction_id: int = Field(description="The positive side (money arriving)")
    confidence: Literal["certain", "likely"]
    reason: str


class PaymentDetailLink(BaseModel):
    paypal_transaction_id: int = Field(description="The row on the PayPal list (the detail)")
    bank_transaction_id: int = Field(description="The Sparkasse/N26/Commerzbank booking it explains")
    confidence: Literal["certain", "likely"]
    reason: str


@mcp.tool()
def link_payment_details(links: list[PaymentDetailLink]) -> str:
    """Tell the app that a PayPal payment is the same payment as a bank booking (batch).

    The bank booking is the money that moved; the PayPal row only explains it (merchant,
    category), so it is not counted a second time. Amount must be equal, both money out, within
    ten days. A PayPal transaction number found on the bank booking is proof (`certain`).
    """
    results = []
    with SessionLocal() as db:
        for link in links:
            res = linking.link_mirror(
                db, link.paypal_transaction_id, link.bank_transaction_id, link.confidence, link.reason
            )
            results.append(res.message)
    return "\n".join(results)


@mcp.tool()
def link_receipts(links: list[ReceiptLink]) -> str:
    """Link receipts to the bank transactions that paid them (batch). Amounts must be equal.

    Use 'certain' only when amount AND identity agree (payment reference, or same merchant and
    a plausible date). Use 'likely' when unsure; the household is then asked yes/no.
    Never force a link: a wrong link is worse than a question.
    """
    results = []
    with SessionLocal() as db:
        for link in links:
            res = linking.link_receipt(
                db, link.transaction_id, link.receipt_id, link.confidence, link.reason
            )
            results.append(res.message)
    return "\n".join(results)


@mcp.tool()
def link_transfers(links: list[TransferLink]) -> str:
    """Pair the two sides of a transfer between the household's own accounts (batch).

    E.g. -500 leaving Sparkasse and +500 arriving on N26. Amounts must be equal, and the two
    sides must be on different statements.
    """
    results = []
    with SessionLocal() as db:
        for link in links:
            res = linking.link_transfer(
                db,
                link.outgoing_transaction_id,
                link.incoming_transaction_id,
                link.confidence,
                link.reason,
            )
            results.append(res.message)
    return "\n".join(results)


class CategoryChange(BaseModel):
    ref: str = Field(description="Entry reference exactly as listed, e.g. i123 or t45")
    category: str = Field(description="Category key from the CATEGORIES list")


@mcp.tool()
def apply_recategorization(changes: list[CategoryChange]) -> str:
    """Move entries to a different category. Send only the entries that should CHANGE.

    Unknown keys, wrong income/expense type and transfers are rejected with the reason.
    """
    with SessionLocal() as db:
        applied, rejected = recategorize.apply_changes(db, [c.model_dump() for c in changes])
    pathlib.Path(os.environ["FIRE_RESULT_FILE"]).write_text(
        json.dumps({"applied": applied, "rejected": rejected}), encoding="utf-8"
    )
    return f"Applied {applied}." + (f" Rejected: {'; '.join(rejected)}" if rejected else "")


if __name__ == "__main__":
    mcp.run(transport="stdio")
