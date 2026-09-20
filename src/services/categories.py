"""The household's editable category list.

Categories are data, not code: the extraction prompts are generated from this table, receipts and
bank transactions store the category `key`, and the dashboards read labels/flow/fixed from here.
Keys are stable ids; renaming only changes the label. Merging or deleting moves the entries.
"""

import re
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBInventoryItem, DBSpendCategory
from services.category_seed import SEED

UNCATEGORIZED_KEY = "uncategorized"
FLOWS = ("expense", "income")
_LEGACY_BY_KEY = {row[0]: row[6] for row in SEED}


class CategoryError(ValueError):
    """A category change the household asked for cannot be done; the message says why."""


def seed_categories(db: Session) -> None:
    """Fill an empty table with the starting set (fresh databases and tests)."""
    if db.query(DBSpendCategory).count():
        return
    for order, (key, label, group, flow, fixed, description, _legacy) in enumerate(SEED):
        db.add(
            DBSpendCategory(
                key=key, label=label, group_name=group, flow=flow, fixed=fixed,
                description=description, sort_order=order * 10, active=True,
            )
        )
    db.commit()


def category_map(db: Session, include_inactive: bool = False) -> dict[str, DBSpendCategory]:
    query = db.query(DBSpendCategory).order_by(DBSpendCategory.sort_order, DBSpendCategory.key)
    if not include_inactive:
        query = query.filter(DBSpendCategory.active.is_(True))
    return {c.key: c for c in query.all()}


def legacy_item_category(key: str | None) -> str:
    """Coarse pantry category (Food, Drinks, ...) for the Inventory pages. Custom keys: Other."""
    return _LEGACY_BY_KEY.get(key or "", "Other")


def prompt_block(db: Session) -> str:
    """The category list as Claude reads it. Always current: it is rebuilt for every run."""
    lines = [
        "## CATEGORIES",
        "Use ONLY these keys (left of the dash) for every category field. Pick the most specific "
        "one. Categories marked (income) are for money coming in only.",
    ]
    current_group = None
    for c in category_map(db).values():
        if c.group_name != current_group:
            current_group = c.group_name
            lines.append(f"\n### {current_group}")
        tag = " (income)" if c.flow == "income" else ""
        lines.append(f"- {c.key}{tag} - {c.label}: {c.description or ''}".rstrip(": "))
    return "\n".join(lines)


def validate_key(cats: dict[str, DBSpendCategory], key: str | None, flow: str) -> str | None:
    """Return an error message if `key` cannot be used with `flow`, else None."""
    if key is None:
        return "is missing a category"
    cat = cats.get(key)
    if cat is None:
        options = ", ".join(k for k, c in cats.items() if c.flow == flow)
        return f"has unknown category '{key}'. Valid {flow} keys: {options}"
    if cat.flow != flow:
        return f"category '{key}' is an {cat.flow} category but this entry is {flow}"
    return None


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return slug or "category"


@dataclass
class Usage:
    items: int
    transactions: int


def usage_counts(db: Session) -> dict[str | None, Usage]:
    counts: dict[str | None, Usage] = {}
    for key, n in db.query(DBInventoryItem.spend_category, func.count()).group_by(DBInventoryItem.spend_category):
        counts.setdefault(key, Usage(0, 0)).items = n
    for key, n in db.query(DBBankTransaction.category, func.count()).group_by(DBBankTransaction.category):
        counts.setdefault(key, Usage(0, 0)).transactions = n
    return counts


def create_category(
    db: Session, *, label: str, group_name: str, flow: str = "expense",
    description: str = "", fixed: bool = False, key: str | None = None,
) -> DBSpendCategory:
    if flow not in FLOWS:
        raise CategoryError(f"flow must be one of {FLOWS}")
    if not label.strip() or not group_name.strip():
        raise CategoryError("A category needs a name and a group.")
    key = slugify(key or label)
    if key == UNCATEGORIZED_KEY or db.get(DBSpendCategory, key):
        raise CategoryError(f"A category with the key '{key}' already exists.")
    last = db.query(func.max(DBSpendCategory.sort_order)).scalar() or 0
    cat = DBSpendCategory(
        key=key, label=label.strip(), group_name=group_name.strip(), flow=flow,
        fixed=fixed, description=description.strip(), sort_order=last + 10, active=True,
    )
    db.add(cat)
    db.commit()
    return cat


def update_category(db: Session, key: str, **fields) -> DBSpendCategory:
    cat = db.get(DBSpendCategory, key)
    if cat is None:
        raise CategoryError(f"Unknown category '{key}'.")
    if "flow" in fields and fields["flow"] != cat.flow:
        raise CategoryError("A category's type (income/expense) cannot change; create a new one.")
    for name in ("label", "group_name", "description", "fixed", "active", "sort_order"):
        if fields.get(name) is not None:
            setattr(cat, name, fields[name])
    db.commit()
    return cat


def _touched_statements(db: Session, key: str):
    ids = {
        t.statement_id
        for t in db.query(DBBankTransaction.statement_id).filter(DBBankTransaction.category == key)
    }
    return ids


def _reassign(db: Session, source: str, target: str | None) -> tuple[int, int]:
    statement_ids = _touched_statements(db, source)
    items = db.query(DBInventoryItem).filter(DBInventoryItem.spend_category == source).update(
        {"spend_category": target, "category": legacy_item_category(target)}
    )
    txs = db.query(DBBankTransaction).filter(DBBankTransaction.category == source).update(
        {"category": target}
    )
    db.flush()
    # Imported here: the statement store imports this module for validation (avoids a cycle).
    from services.statement_store import sync_statement_json

    # The Statements page reads a derived copy that carries categories.
    for statement in db.query(DBBankStatement).filter(DBBankStatement.id.in_(statement_ids)):
        sync_statement_json(db, statement)
    return items, txs


def merge_category(db: Session, source: str, target: str) -> tuple[int, int]:
    """Move every entry from `source` to `target` and remove `source`."""
    src, dst = db.get(DBSpendCategory, source), db.get(DBSpendCategory, target)
    if src is None or dst is None or source == target:
        raise CategoryError("Pick two different existing categories to merge.")
    if src.flow != dst.flow:
        raise CategoryError("Income and expense categories cannot be merged.")
    moved = _reassign(db, source, target)
    db.delete(src)
    db.commit()
    return moved


def delete_category(db: Session, key: str) -> tuple[int, int]:
    """Delete a category. Entries that used it become uncategorized (a Claude re-check can fix)."""
    cat = db.get(DBSpendCategory, key)
    if cat is None:
        raise CategoryError(f"Unknown category '{key}'.")
    moved = _reassign(db, key, None)
    db.delete(cat)
    db.commit()
    return moved


# ── changing one entry by hand ────────────────────────────────────────────────────────────────
NO_CATEGORY_KINDS = ("internal_transfer", "investment")  # money moved, not spent
INCOME_KINDS = ("income", "refund")


def _check_choice(cats: dict[str, DBSpendCategory], key: str, flow: str) -> None:
    """Plain-language refusal for a category picked by hand."""
    cat = cats.get(key)
    if cat is None:
        raise CategoryError(f"There is no active category '{key}'.")
    if cat.flow != flow:
        kind = "an income" if cat.flow == "income" else "an expense"
        raise CategoryError(f"'{cat.label}' is {kind} category, but this entry is money {'in' if flow == 'income' else 'out'}.")


def set_transaction_category(db: Session, tx_id: int, key: str) -> DBBankTransaction:
    """The household picked a category for one bank booking. Same rules as the extraction."""
    tx = db.get(DBBankTransaction, tx_id)
    if tx is None:
        raise LookupError(f"No transaction #{tx_id}.")
    if tx.kind in NO_CATEGORY_KINDS:
        raise CategoryError("Transfers and investments are not spending, so they have no category.")
    flow = "income" if tx.kind in INCOME_KINDS or tx.amount > 0 else "expense"
    _check_choice(category_map(db), key, flow)
    tx.category = key
    db.flush()
    # Imported here: the statement store imports this module for validation (avoids a cycle).
    from services.statement_store import sync_statement_json

    sync_statement_json(db, tx.statement)  # the Statements page reads this copy
    db.commit()
    return tx


def set_item_category(db: Session, item_id: int, key: str) -> DBInventoryItem:
    """The household picked a category for one receipt item."""
    item = db.get(DBInventoryItem, item_id)
    if item is None:
        raise LookupError(f"No receipt item #{item_id}.")
    _check_choice(category_map(db), key, "expense")
    item.spend_category, item.category = key, legacy_item_category(key)
    db.commit()
    return item
