"""Validate and persist one statement read by Claude.

Claude proposes, this code checks (balances must add up) and stores. It also keeps the legacy
`statements.transactions` JSON in sync so the existing dashboards keep working while they
are migrated to the `bank_transactions` table.
"""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import (
    DBBankStatement,
    DBBankTransaction,
    DBMonthlyStat,
    DBReceipt,
    DBReviewQuestion,
)
from models.statement import StatementSubmission, TxKind
from services.categories import category_map, validate_key

BALANCE_TOLERANCE_EUR = 0.02
MAX_PERIOD_SPREAD_DAYS = 40
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class StatementOutcome:
    ok: bool
    message: str
    statement_id: int | None = None
    duplicate: bool = False
    month_label: str | None = None
    warnings: list[str] = field(default_factory=list)


def statement_month(sub: StatementSubmission) -> tuple[int, int]:
    """(year, month) the statement belongs to: where most bookings fall, not the issue date."""
    counts = Counter((t.booking_date.year, t.booking_date.month) for t in sub.transactions)
    top = max(counts.values())
    leaders = [ym for ym, n in counts.items() if n == top]
    if len(leaders) == 1:
        return leaders[0]
    return (sub.period_end.year, sub.period_end.month)


NO_CATEGORY_KINDS = (TxKind.INTERNAL_TRANSFER, TxKind.INVESTMENT)  # money moved, not spent
DEFAULT_CATEGORY_FOR_KIND = {TxKind.FEE: "bank_fees", TxKind.CASH: "cash"}
INCOME_KINDS = (TxKind.INCOME, TxKind.REFUND)


def _category_problems(sub: StatementSubmission, categories: dict) -> list[str]:
    problems = []
    for t in sub.transactions:
        if t.kind in NO_CATEGORY_KINDS:
            continue
        who = f"{t.booking_date} {t.counterparty} {t.amount:+.2f}"
        if t.category is None:
            if t.kind in DEFAULT_CATEGORY_FOR_KIND or t.kind == TxKind.OTHER:
                continue
            problems.append(f"Entry {who} is missing a category.")
            continue
        flow = "income" if t.kind in INCOME_KINDS or (t.kind == TxKind.OTHER and t.amount > 0) else "expense"
        problem = validate_key(categories, t.category, flow)
        if problem:
            problems.append(f"Entry {who} {problem}.")
    return problems


def find_problems(sub: StatementSubmission, categories: dict | None = None) -> list[str]:
    """Hard problems: the statement must not be stored while any of these hold."""
    problems: list[str] = []
    if not sub.transactions:
        return ["No transactions were extracted."]
    if sub.period_start > sub.period_end:
        problems.append(f"period_start {sub.period_start} is after period_end {sub.period_end}.")

    dates = [t.booking_date for t in sub.transactions]
    if (max(dates) - min(dates)).days > MAX_PERIOD_SPREAD_DAYS:
        problems.append(
            f"Bookings span {min(dates)} to {max(dates)}, more than {MAX_PERIOD_SPREAD_DAYS} days. "
            "This looks like mixed statements or a misread date."
        )

    if sub.opening_balance is not None and sub.closing_balance is not None:
        total = round(sum(t.amount for t in sub.transactions), 2)
        expected = round(sub.closing_balance - sub.opening_balance, 2)
        if abs(total - expected) > BALANCE_TOLERANCE_EUR:
            problems.append(
                f"Bookings sum to {total:+.2f} but closing - opening balance is {expected:+.2f} "
                f"(difference {total - expected:+.2f}). Re-check for a missed or duplicated "
                "entry, a wrong sign, or a misread amount."
            )
    if categories is not None:
        problems.extend(_category_problems(sub, categories))
    return problems


def find_warnings(db: Session, owner: str, sub: StatementSubmission, year: int, month: int) -> list[str]:
    """Soft problems worth a human look: the balance chain to neighbouring statements."""
    warnings: list[str] = []
    if sub.opening_balance is None or sub.closing_balance is None:
        return warnings
    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)
    base = db.query(DBBankStatement).filter(
        DBBankStatement.bank == sub.bank.value, DBBankStatement.owner == owner
    )
    prev = base.filter(
        DBBankStatement.year == prev_y, DBBankStatement.month == MONTH_ABBR[prev_m - 1]
    ).first()
    nxt = base.filter(
        DBBankStatement.year == next_y, DBBankStatement.month == MONTH_ABBR[next_m - 1]
    ).first()
    if prev and abs(prev.closing_balance - sub.opening_balance) > BALANCE_TOLERANCE_EUR:
        warnings.append(
            f"Opening balance {sub.opening_balance:.2f} differs from the closing balance "
            f"{prev.closing_balance:.2f} of the {MONTH_ABBR[prev_m - 1]} {prev_y} statement."
        )
    if nxt and abs(nxt.starting_balance - sub.closing_balance) > BALANCE_TOLERANCE_EUR:
        warnings.append(
            f"Closing balance {sub.closing_balance:.2f} differs from the opening balance "
            f"{nxt.starting_balance:.2f} of the {MONTH_ABBR[next_m - 1]} {next_y} statement."
        )
    return warnings


def sync_statement_json(db: Session, statement: DBBankStatement) -> None:
    """Rebuild the legacy JSON copy (used by the existing dashboards) from bank_transactions."""
    rows = (
        db.query(DBBankTransaction)
        .filter(DBBankTransaction.statement_id == statement.id)
        .order_by(DBBankTransaction.booking_date, DBBankTransaction.id)
        .all()
    )
    statement.transactions = [
        {
            "date": r.booking_date.strftime("%d.%m.%Y"),
            "description": f"{r.counterparty}: {r.description}",
            "amount": r.amount,
            "category": None,
            "inventory_purchase_id": r.receipt_id,
            "counterparty": r.counterparty,
            "kind": r.kind,
            "transfer_group": r.transfer_group,
        }
        for r in rows
    ]
    # Cached month statistics are derived from this data: never serve a stale copy.
    db.query(DBMonthlyStat).filter(
        DBMonthlyStat.month == statement.month, DBMonthlyStat.year == statement.year
    ).delete()


PARTIAL_NOTE = "No opening/closing balance available"


def _has_balances(statement: DBBankStatement) -> bool:
    # Missing balances are stored as 0.0, so 0.0 cannot tell "unknown" from "zero": rely on the
    # note written when the statement was saved without both balances.
    return PARTIAL_NOTE not in (statement.review_note or "")


def _link_key(tx: DBBankTransaction) -> tuple:
    return (tx.booking_date, round(tx.amount, 2), tx.description)


def _brief(tx: DBBankTransaction) -> str:
    extra = f" (bought {tx.purchase_date})" if tx.purchase_date else ""
    return (
        f"#{tx.id} | {tx.booking_date}{extra} | {tx.amount:+.2f} | {tx.counterparty} | "
        f"{tx.kind}" + (f" | ref {tx.payment_reference}" if tx.payment_reference else "")
    )


def save_statement(
    db: Session,
    *,
    owner: str,
    source_path: str,
    file_hash: str,
    sub: StatementSubmission,
    review_note: str | None = None,
) -> StatementOutcome:
    same_file = db.query(DBBankStatement).filter(DBBankStatement.file_hash == file_hash).first()
    if same_file:
        return StatementOutcome(
            ok=True,
            duplicate=True,
            statement_id=same_file.id,
            message=f"Already stored as statement #{same_file.id}. Nothing to do.",
        )

    problems = find_problems(sub, categories=category_map(db))
    if problems and not review_note:
        return StatementOutcome(
            ok=False,
            message="NOT SAVED. Fix these and call save_statement again:\n- "
            + "\n- ".join(problems),
        )

    year, month = statement_month(sub)
    label = MONTH_ABBR[month - 1]
    warnings = find_warnings(db, owner, sub, year, month)
    has_balances = sub.opening_balance is not None and sub.closing_balance is not None
    if not has_balances:
        warnings.append(
            f"{PARTIAL_NOTE} (partial statement or screenshots): "
            "completeness could not be verified."
        )

    notes = []
    if problems:
        notes.append(f"{review_note} | checks failed: " + " ; ".join(problems))
    notes.extend(warnings)

    # Re-import of the same bank/owner/month replaces the old copy but keeps links and answers.
    kept_links: dict[tuple, tuple] = {}
    kept_ids: dict[tuple, int] = {}
    old = (
        db.query(DBBankStatement)
        .filter(
            DBBankStatement.bank == sub.bank.value,
            # owner IS NULL: imported by the old parser before owners existed; replace it too
            or_(DBBankStatement.owner == owner, DBBankStatement.owner.is_(None)),
            DBBankStatement.year == year,
            DBBankStatement.month == label,
        )
        .first()
    )
    if old is not None and not has_balances and _has_balances(old):
        # Screenshots without balances must never overwrite a complete, verified statement.
        return StatementOutcome(
            ok=True,
            duplicate=True,
            statement_id=old.id,
            message=(
                f"NOTHING IMPORTED: a complete statement for {sub.bank.value} {label} {year} "
                f"already exists (#{old.id}, balances verified) and this partial document has no "
                "balances to verify against, so it would overwrite better data. Stop here; do "
                "not link anything."
            ),
        )
    old_question_rows: list[DBReviewQuestion] = []
    old_linked_receipts: set[int] = set()
    if old:
        old_linked_receipts = {t.receipt_id for t in old.bank_transactions if t.receipt_id}
        old_ids = [t.id for t in old.bank_transactions]
        for t in old.bank_transactions:
            kept_ids[_link_key(t)] = t.id
            if t.receipt_id is not None or t.transfer_group is not None:
                kept_links[_link_key(t)] = (
                    t.receipt_id, t.link_status, t.link_reason, t.transfer_group
                )
        old_question_rows = (
            db.query(DBReviewQuestion)
            .filter(DBReviewQuestion.transaction_id.in_(old_ids))
            .all()
            if old_ids
            else []
        )
        old_question_data = [
            (q.kind, q.transaction_id, q.receipt_id, q.other_transaction_id, q.question, q.status,
             q.created_at, q.answered_at)
            for q in old_question_rows
        ]
        for q in old_question_rows:
            db.delete(q)
        db.delete(old)
        db.flush()
    else:
        old_question_data = []

    statement = DBBankStatement(
        bank=sub.bank.value,
        month=label,
        year=year,
        starting_balance=sub.opening_balance if sub.opening_balance is not None else 0.0,
        closing_balance=sub.closing_balance if sub.closing_balance is not None else 0.0,
        transactions=[],
        owner=owner,
        source_path=source_path,
        file_hash=file_hash,
        period_start=sub.period_start,
        period_end=sub.period_end,
        status="needs_review" if notes else "ok",
        review_note=" || ".join(notes) if notes else None,
    )
    db.add(statement)
    db.flush()

    rows: list[DBBankTransaction] = []
    for line in sub.transactions:
        row = DBBankTransaction(
            statement_id=statement.id,
            booking_date=line.booking_date,
            purchase_date=line.purchase_date,
            amount=line.amount,
            counterparty=line.counterparty,
            description=line.description,
            channel=line.channel,
            payment_reference=line.payment_reference,
            kind=line.kind.value,
            category=(
                None
                if line.kind in NO_CATEGORY_KINDS
                else line.category or DEFAULT_CATEGORY_FOR_KIND.get(line.kind)
            ),
        )
        link = kept_links.get(_link_key(row))
        if link:
            row.receipt_id, row.link_status, row.link_reason, row.transfer_group = link
        db.add(row)
        rows.append(row)
    db.flush()

    # Carry answered/open questions over to the re-imported rows.
    new_id_by_key = {_link_key(r): r.id for r in rows}
    old_key_by_id = {v: k for k, v in kept_ids.items()}
    for kind, tx_id, rc_id, other_id, text, status, created, answered in old_question_data:
        key = old_key_by_id.get(tx_id)
        new_tx = new_id_by_key.get(key) if key else None
        if new_tx is None:
            continue
        other_key = old_key_by_id.get(other_id) if other_id else None
        new_other = new_id_by_key.get(other_key) if other_key else None
        db.add(
            DBReviewQuestion(
                kind=kind, transaction_id=new_tx, receipt_id=rc_id,
                other_transaction_id=new_other, question=text, status=status,
                created_at=created, answered_at=answered,
            )
        )

    # A re-import may drop a booking a receipt was linked to; clear that receipt's flag.
    still_linked = {r.receipt_id for r in rows if r.receipt_id}
    for rid in old_linked_receipts - still_linked:
        receipt = db.get(DBReceipt, rid)
        if receipt:
            receipt.bank_statement_linked = False

    sync_statement_json(db, statement)
    db.commit()

    listing = "\n".join(_brief(r) for r in sorted(rows, key=lambda r: (r.booking_date, r.id)))
    msg = (
        f"{'Saved FOR REVIEW' if notes else 'Saved'} as statement #{statement.id} "
        f"({sub.bank.value} {label} {year}, {len(rows)} transactions).\n"
        + ("Warnings:\n- " + "\n- ".join(notes) + "\n" if notes else "")
        + "Stored transactions:\n"
        + listing
    )
    return StatementOutcome(
        ok=True, message=msg, statement_id=statement.id, month_label=f"{label} {year}",
        warnings=notes,
    )
