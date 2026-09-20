"""Validate and persist one extracted receipt.

This is the "rules" layer behind the Claude tool: Claude proposes, this code checks.
It has no dependency on Claude, so it is unit-testable and reusable.
"""

import datetime
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from database.models import DBInventoryItem, DBReceipt
from models.inventory import ItemCategory, ReceiptSubmission

# Rounding noise on receipts is at most a cent or two; more than this is a real misread.
SUM_TOLERANCE_EUR = 0.02
MAX_RECEIPT_AGE_DAYS = 366 * 5


@dataclass
class SaveOutcome:
    ok: bool
    message: str
    receipt_id: int | None = None
    duplicate: bool = False


def find_problems(sub: ReceiptSubmission, today: datetime.date | None = None) -> list[str]:
    """Return human-readable problems; an empty list means the receipt is consistent."""
    today = today or datetime.date.today()
    problems: list[str] = []

    if not sub.items:
        problems.append("No items were extracted.")

    if sub.purchase_date > today:
        problems.append(f"purchase_date {sub.purchase_date} is in the future.")
    elif (today - sub.purchase_date).days > MAX_RECEIPT_AGE_DAYS:
        problems.append(f"purchase_date {sub.purchase_date} is implausibly old.")

    if sub.total_amount <= 0:
        problems.append(f"total_amount {sub.total_amount} must be positive.")

    for line in sub.items:
        if line.unit_price < 0 and line.category != ItemCategory.DEPOSIT:
            problems.append(
                f"'{line.name}' has a negative price but is not a Deposit line. "
                "Discounts belong in the 'discount' field of the item above them."
            )

    computed = round(sum(line.line_total for line in sub.items), 2)
    if abs(computed - sub.total_amount) > SUM_TOLERANCE_EUR:
        problems.append(
            f"Items sum to {computed:.2f} (quantity * unit_price - discount) but total_amount is "
            f"{sub.total_amount:.2f} (difference {computed - sub.total_amount:+.2f}). "
            "Re-check for a missed/duplicated line, a wrong quantity, a discount attached to "
            "the wrong item, or a misread price."
        )
    return problems


def find_duplicate(db: Session, sub: ReceiptSubmission, file_hash: str) -> DBReceipt | None:
    by_file = db.query(DBReceipt).filter(DBReceipt.file_hash == file_hash).first()
    if by_file:
        return by_file
    query = db.query(DBReceipt).filter(
        DBReceipt.store_name == sub.store_name,
        DBReceipt.purchase_date == sub.purchase_date,
        DBReceipt.total_amount == sub.total_amount,
    )
    if sub.receipt_number:
        # Same shop, day and total but a different Bon number is a genuinely different purchase.
        query = query.filter(DBReceipt.receipt_number == sub.receipt_number)
    return query.first()


def save_receipt(
    db: Session,
    *,
    owner: str,
    source_path: str,
    file_hash: str,
    sub: ReceiptSubmission,
    review_note: str | None = None,
) -> SaveOutcome:
    """Store the receipt if it is consistent, or flag it for review if Claude says it can't be.

    Without `review_note`, any problem rejects the save and the message tells Claude what to fix.
    With `review_note`, the receipt is stored with status 'needs_review' so a human can look.
    """
    duplicate = find_duplicate(db, sub, file_hash)
    if duplicate:
        return SaveOutcome(
            ok=True,
            duplicate=True,
            receipt_id=duplicate.id,
            message=f"Already stored as receipt #{duplicate.id}. Nothing to do.",
        )

    problems = find_problems(sub)
    if problems and not review_note:
        return SaveOutcome(
            ok=False,
            message="NOT SAVED. Fix these and call save_receipt again:\n- " + "\n- ".join(problems),
        )

    status = "needs_review" if problems else "ok"
    note = None
    if problems:
        note = f"{review_note} | checks failed: " + " ; ".join(problems)

    receipt = DBReceipt(
        store_name=sub.store_name,
        total_amount=sub.total_amount,
        total_discount=round(sum(line.discount for line in sub.items), 2),
        purchase_date=sub.purchase_date,
        bank_statement_linked=False,
        owner=owner,
        source_path=source_path,
        file_hash=file_hash,
        receipt_number=sub.receipt_number,
        payment_reference=sub.payment_reference,
        payment_method=sub.payment_method,
        status=status,
        review_note=note,
    )
    db.add(receipt)
    db.flush()

    for line in sub.items:
        expiry = None
        if line.estimated_shelf_life_days is not None:
            expiry = sub.purchase_date + timedelta(days=line.estimated_shelf_life_days)
        db.add(
            DBInventoryItem(
                receipt_id=receipt.id,
                name=line.name,
                brand=line.brand,
                quantity=line.quantity,
                unit_cost=line.unit_price,
                discount=line.discount,
                category=line.category.value,
                storage_condition=line.storage_condition.value,
                date_purchased=sub.purchase_date,
                date_expiry=expiry,
            )
        )
    db.commit()

    verb = "Saved" if status == "ok" else "Saved FOR REVIEW"
    return SaveOutcome(
        ok=True,
        receipt_id=receipt.id,
        message=f"{verb} as receipt #{receipt.id} ({len(sub.items)} items, {sub.total_amount:.2f} EUR).",
    )
