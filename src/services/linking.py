"""Linking receipts <-> bank transactions and transfers between the household's own accounts.

Claude decides *which* things belong together; this module enforces the invariants no model
judgement may break (amounts must agree, nothing is linked twice, answered "no" stays "no")
and turns unsure matches into yes/no questions for the household.
"""

import datetime
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBReceipt, DBReviewQuestion
from services.statement_store import sync_statement_json

AMOUNT_TOLERANCE_EUR = 0.01
MAX_ROWS = 80


@dataclass
class LinkResult:
    ok: bool
    message: str


# ── read tools ────────────────────────────────────────────────────────────────────────────────
def find_receipts(
    db: Session,
    date_from: datetime.date,
    date_to: datetime.date,
    only_unlinked: bool = True,
    amount: float | None = None,
) -> list[dict]:
    query = db.query(DBReceipt).filter(
        DBReceipt.purchase_date >= date_from, DBReceipt.purchase_date <= date_to
    )
    if only_unlinked:
        query = query.filter(DBReceipt.bank_statement_linked == False)  # noqa: E712
    if amount is not None:
        query = query.filter(
            DBReceipt.total_amount.between(abs(amount) - AMOUNT_TOLERANCE_EUR, abs(amount) + AMOUNT_TOLERANCE_EUR)
        )
    rows = query.order_by(DBReceipt.purchase_date, DBReceipt.id).limit(MAX_ROWS).all()
    return [
        {
            "receipt_id": r.id,
            "owner": r.owner,
            "store": r.store_name,
            "purchase_date": r.purchase_date.isoformat(),
            "total": r.total_amount,
            "payment_method": r.payment_method,
            "payment_reference": r.payment_reference,
            "receipt_number": r.receipt_number,
            "linked": r.bank_statement_linked,
        }
        for r in rows
    ]


def find_transactions(
    db: Session,
    date_from: datetime.date,
    date_to: datetime.date,
    only_unlinked: bool = True,
    amount: float | None = None,
    kind: str | None = "spend",
) -> list[dict]:
    """Transactions whose booking date OR purchase date falls in the window."""
    query = (
        db.query(DBBankTransaction, DBBankStatement)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(
            or_(
                DBBankTransaction.booking_date.between(date_from, date_to),
                DBBankTransaction.purchase_date.between(date_from, date_to),
            )
        )
    )
    if kind:
        query = query.filter(DBBankTransaction.kind == kind)
    if only_unlinked:
        query = query.filter(DBBankTransaction.receipt_id.is_(None))
    if amount is not None:
        query = query.filter(
            DBBankTransaction.amount.between(-abs(amount) - AMOUNT_TOLERANCE_EUR, -abs(amount) + AMOUNT_TOLERANCE_EUR)
            | DBBankTransaction.amount.between(abs(amount) - AMOUNT_TOLERANCE_EUR, abs(amount) + AMOUNT_TOLERANCE_EUR)
        )
    rows = query.order_by(DBBankTransaction.booking_date, DBBankTransaction.id).limit(MAX_ROWS).all()
    return [
        {
            "transaction_id": t.id,
            "bank": s.bank,
            "booking_date": t.booking_date.isoformat(),
            "purchase_date": t.purchase_date.isoformat() if t.purchase_date else None,
            "amount": t.amount,
            "counterparty": t.counterparty,
            "channel": t.channel,
            "payment_reference": t.payment_reference,
            "kind": t.kind,
            "description": t.description[:160],
            "linked_receipt_id": t.receipt_id,
            "transfer_group": t.transfer_group,
        }
        for t, s in rows
    ]


# ── questions ─────────────────────────────────────────────────────────────────────────────────
def _pair_already_asked(db: Session, kind: str, tx_id: int, other: int | None, receipt_id: int | None) -> DBReviewQuestion | None:
    query = db.query(DBReviewQuestion).filter(
        DBReviewQuestion.kind == kind,
        DBReviewQuestion.transaction_id == tx_id,
        DBReviewQuestion.status.in_(["open", "no", "yes"]),
    )
    if receipt_id is not None:
        query = query.filter(DBReviewQuestion.receipt_id == receipt_id)
    if other is not None:
        query = query.filter(DBReviewQuestion.other_transaction_id == other)
    return query.first()


def _close_open_questions_for(db: Session, tx_ids: list[int], receipt_id: int | None) -> None:
    query = db.query(DBReviewQuestion).filter(DBReviewQuestion.status == "open")
    conditions = [DBReviewQuestion.transaction_id.in_(tx_ids), DBReviewQuestion.other_transaction_id.in_(tx_ids)]
    if receipt_id is not None:
        conditions.append(DBReviewQuestion.receipt_id == receipt_id)
    for q in query.filter(or_(*conditions)).all():
        q.status = "superseded"  # the item got linked another way; not a household "no"
        q.answered_at = datetime.datetime.utcnow()


# ── receipt <-> transaction ───────────────────────────────────────────────────────────────────
def link_receipt(
    db: Session, tx_id: int, receipt_id: int, confidence: str, reason: str
) -> LinkResult:
    tx = db.get(DBBankTransaction, tx_id)
    receipt = db.get(DBReceipt, receipt_id)
    if tx is None:
        return LinkResult(False, f"REJECTED: transaction #{tx_id} does not exist.")
    if receipt is None:
        return LinkResult(False, f"REJECTED: receipt #{receipt_id} does not exist.")
    if tx.amount >= 0:
        return LinkResult(False, f"REJECTED: transaction #{tx_id} is money IN ({tx.amount:+.2f}); receipts match payments.")
    if abs(abs(tx.amount) - receipt.total_amount) > AMOUNT_TOLERANCE_EUR:
        return LinkResult(
            False,
            f"REJECTED: amounts differ - transaction #{tx_id} is {abs(tx.amount):.2f} but receipt "
            f"#{receipt_id} is {receipt.total_amount:.2f}. Only equal amounts can be linked.",
        )
    if tx.receipt_id is not None:
        return LinkResult(False, f"REJECTED: transaction #{tx_id} is already linked to receipt #{tx.receipt_id}.")
    if receipt.bank_statement_linked:
        return LinkResult(False, f"REJECTED: receipt #{receipt_id} is already linked to a transaction.")

    asked = _pair_already_asked(db, "receipt_match", tx_id, None, receipt_id)
    if asked and asked.status == "no":
        return LinkResult(False, f"SKIPPED: the household already answered NO for transaction #{tx_id} / receipt #{receipt_id}.")

    if confidence == "certain":
        tx.receipt_id = receipt_id
        tx.link_status = "auto"
        tx.link_reason = reason[:300]
        receipt.bank_statement_linked = True
        _close_open_questions_for(db, [tx_id], receipt_id)
        sync_statement_json(db, tx.statement)
        db.commit()
        return LinkResult(True, f"LINKED transaction #{tx_id} <-> receipt #{receipt_id}.")

    if asked:
        return LinkResult(True, f"Question already open for transaction #{tx_id} / receipt #{receipt_id}.")
    question = (
        f"Is the {abs(tx.amount):.2f} EUR payment to {tx.counterparty} booked on {tx.booking_date}"
        + (f" (bought {tx.purchase_date})" if tx.purchase_date else "")
        + f" the {receipt.store_name} receipt from {receipt.purchase_date} ({receipt.total_amount:.2f} EUR)?"
        + (f" Why unsure: {reason}" if reason else "")
    )
    db.add(DBReviewQuestion(kind="receipt_match", transaction_id=tx_id, receipt_id=receipt_id, question=question[:600]))
    db.commit()
    return LinkResult(True, f"QUESTION created for transaction #{tx_id} / receipt #{receipt_id} (not linked yet).")


# ── transfer <-> transfer (between the household's own accounts) ──────────────────────────────
def link_transfer(db: Session, out_tx_id: int, in_tx_id: int, confidence: str, reason: str) -> LinkResult:
    out_tx = db.get(DBBankTransaction, out_tx_id)
    in_tx = db.get(DBBankTransaction, in_tx_id)
    if out_tx is None or in_tx is None:
        return LinkResult(False, "REJECTED: one of the transactions does not exist.")
    if not (out_tx.amount < 0 < in_tx.amount):
        return LinkResult(False, "REJECTED: first id must be the outgoing (negative), second the incoming (positive) side.")
    if abs(abs(out_tx.amount) - in_tx.amount) > AMOUNT_TOLERANCE_EUR:
        return LinkResult(False, f"REJECTED: amounts differ ({abs(out_tx.amount):.2f} vs {in_tx.amount:.2f}).")
    if out_tx.statement_id == in_tx.statement_id:
        return LinkResult(False, "REJECTED: both sides are on the same statement; a transfer connects two different accounts.")
    if out_tx.transfer_group is not None or in_tx.transfer_group is not None:
        return LinkResult(False, "REJECTED: one side is already part of a transfer pair.")

    asked = _pair_already_asked(db, "transfer_match", out_tx_id, in_tx_id, None)
    if asked and asked.status == "no":
        return LinkResult(False, "SKIPPED: the household already answered NO for this pair.")

    if confidence == "certain":
        for tx in (out_tx, in_tx):
            tx.transfer_group = out_tx.id
            tx.kind = "internal_transfer"
            tx.link_status = "auto"
            tx.link_reason = reason[:300]
        _close_open_questions_for(db, [out_tx_id, in_tx_id], None)
        sync_statement_json(db, out_tx.statement)
        sync_statement_json(db, in_tx.statement)
        db.commit()
        return LinkResult(True, f"LINKED transfer #{out_tx_id} -> #{in_tx_id}.")

    if asked:
        return LinkResult(True, "Question already open for this pair.")
    out_bank = db.get(DBBankStatement, out_tx.statement_id).bank
    in_bank = db.get(DBBankStatement, in_tx.statement_id).bank
    question = (
        f"Is the {abs(out_tx.amount):.2f} EUR leaving {out_bank} on {out_tx.booking_date} the same "
        f"money as the {in_tx.amount:.2f} EUR arriving on {in_bank} on {in_tx.booking_date} "
        f"(a transfer between your own accounts)?" + (f" Why unsure: {reason}" if reason else "")
    )
    db.add(DBReviewQuestion(kind="transfer_match", transaction_id=out_tx_id, other_transaction_id=in_tx_id, question=question[:600]))
    db.commit()
    return LinkResult(True, "QUESTION created for the transfer pair (not linked yet).")


# ── answering ─────────────────────────────────────────────────────────────────────────────────
def open_questions(db: Session) -> list[dict]:
    rows = db.query(DBReviewQuestion).filter(DBReviewQuestion.status == "open").order_by(DBReviewQuestion.id).all()
    return [
        {
            "id": q.id,
            "kind": q.kind,
            "question": q.question,
            "transaction_id": q.transaction_id,
            "receipt_id": q.receipt_id,
            "other_transaction_id": q.other_transaction_id,
            "created_at": q.created_at.isoformat() + "Z" if q.created_at else None,
        }
        for q in rows
    ]


def answer_question(db: Session, question_id: int, yes: bool) -> LinkResult:
    q = db.get(DBReviewQuestion, question_id)
    if q is None:
        return LinkResult(False, f"Question #{question_id} does not exist.")
    if q.status != "open":
        return LinkResult(False, f"Question #{question_id} was already answered ({q.status}).")

    if not yes:
        q.status = "no"
        q.answered_at = datetime.datetime.utcnow()
        db.commit()
        return LinkResult(True, "Noted: not linked, and I won't ask about this pair again.")

    q.status = "yes"
    q.answered_at = datetime.datetime.utcnow()
    db.flush()
    if q.kind == "receipt_match":
        tx = db.get(DBBankTransaction, q.transaction_id)
        receipt = db.get(DBReceipt, q.receipt_id)
        if tx.receipt_id is not None or receipt.bank_statement_linked:
            db.commit()
            return LinkResult(False, "Already linked in the meantime.")
        tx.receipt_id = receipt.id
        tx.link_status = "confirmed"
        tx.link_reason = "confirmed by household"
        receipt.bank_statement_linked = True
        _close_open_questions_for(db, [tx.id], receipt.id)
        sync_statement_json(db, tx.statement)
    else:
        out_tx = db.get(DBBankTransaction, q.transaction_id)
        in_tx = db.get(DBBankTransaction, q.other_transaction_id)
        if out_tx.transfer_group is not None or in_tx.transfer_group is not None:
            db.commit()
            return LinkResult(False, "Already linked in the meantime.")
        for tx in (out_tx, in_tx):
            tx.transfer_group = out_tx.id
            tx.kind = "internal_transfer"
            tx.link_status = "confirmed"
            tx.link_reason = "confirmed by household"
        _close_open_questions_for(db, [out_tx.id, in_tx.id], None)
        sync_statement_json(db, out_tx.statement)
        sync_statement_json(db, in_tx.statement)
    db.commit()
    return LinkResult(True, "Linked.")


# ── deterministic safety net ──────────────────────────────────────────────────────────────────
PAIRABLE_KINDS = ("internal_transfer", "investment")
PAIR_WINDOW_DAYS = 5


def auto_pair_transfers(db: Session, window_days: int = PAIR_WINDOW_DAYS) -> int:
    """Pair obvious transfers Claude did not: same amount, opposite sign, different statements,
    within a few days, and each side has exactly ONE possible partner. Anything ambiguous is
    left alone (Claude or the household decides). Returns the number of pairs linked.
    """
    open_rows = (
        db.query(DBBankTransaction)
        .filter(
            DBBankTransaction.kind.in_(PAIRABLE_KINDS),
            DBBankTransaction.transfer_group.is_(None),
        )
        .all()
    )
    outs = [t for t in open_rows if t.amount < 0]
    ins = [t for t in open_rows if t.amount > 0]

    def partners(tx: DBBankTransaction, pool: list[DBBankTransaction]) -> list[DBBankTransaction]:
        return [
            other
            for other in pool
            if other.statement_id != tx.statement_id
            and abs(abs(tx.amount) - abs(other.amount)) <= AMOUNT_TOLERANCE_EUR
            and abs((other.booking_date - tx.booking_date).days) <= window_days
        ]

    linked = 0
    for out_tx in outs:
        candidates = partners(out_tx, ins)
        if len(candidates) != 1:
            continue
        in_tx = candidates[0]
        if len(partners(in_tx, outs)) != 1:
            continue  # two outgoing payments could be this incoming one: ambiguous
        result = link_transfer(
            db, out_tx.id, in_tx.id, "certain",
            f"auto: same amount, {window_days} days or less apart, only possible partner",
        )
        linked += 1 if result.ok else 0
    return linked
