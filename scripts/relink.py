"""Re-run the deterministic linking pass and rebuild the dashboard numbers. No Claude, no tokens.

    uv run python scripts/relink.py             # pair obvious transfers, refresh statistics
    uv run python scripts/relink.py --dry-run   # only show what is currently unpaired

Safe to run any time: it only links transfers that have exactly one possible partner (same
amount, opposite sign, different statements, within 5 days) and never touches anything else.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from database.migrate import refresh_derived_data, upgrade_to_head  # noqa: E402
from database.models import DBBankStatement, DBBankTransaction  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.linking import PAIRABLE_KINDS, auto_pair_transfers  # noqa: E402


def show_unpaired(db) -> None:
    rows = (
        db.query(DBBankTransaction, DBBankStatement)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(
            DBBankTransaction.kind.in_(PAIRABLE_KINDS), DBBankTransaction.transfer_group.is_(None)
        )
        .order_by(DBBankTransaction.booking_date)
        .all()
    )
    print(f"{len(rows)} unpaired transfer/investment booking(s):")
    for tx, st in rows:
        print(f"  #{tx.id:<4} {st.bank:<11} {tx.booking_date} {tx.amount:>10.2f}  {tx.kind:<17} {tx.counterparty}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    upgrade_to_head()
    with SessionLocal() as db:
        if args.dry_run:
            show_unpaired(db)
            return
        paired = auto_pair_transfers(db)
    refresh_derived_data()
    with SessionLocal() as db:
        print(f"Paired {paired} transfer(s); statistics will be rebuilt on next view.")
        show_unpaired(db)


if __name__ == "__main__":
    main()
