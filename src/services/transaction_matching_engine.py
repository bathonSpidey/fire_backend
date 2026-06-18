import datetime
from datetime import timedelta

from sqlalchemy import extract
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from database.models import DBBankStatement, DBReceipt


class TransactionMatchingEngine:
    def __init__(self, db: Session):
        self.db = db

    def _parse_bank_date(self, date_str: str) -> datetime.date:
        """Robust helper to parse multiple incoming bank ledger date formats."""
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Could not parse bank statement date format string: '{date_str}'")

    def reconcile_orphans(self, target_year: int) -> int:
        """Finds unlinked receipts and attempts to match them against bank transactions

        using an adaptive, multi-format matching strategy.
        """
        unlinked_receipts = (
            self.db.query(DBReceipt)
            .filter(
                not DBReceipt.bank_statement_linked,
                extract("year", DBReceipt.purchase_date) == target_year,
            )
            .all()
        )

        if not unlinked_receipts:
            return 0

        statements = (
            self.db.query(DBBankStatement).filter(DBBankStatement.year == target_year).all()
        )

        links_established = 0

        for receipt in unlinked_receipts:
            # Create standardized strings to look for embedded dates (e.g., "02.04.2026" or "2026-04-02")
            receipt_dot_str = receipt.purchase_date.strftime("%d.%m.%Y")
            receipt_dash_str = receipt.purchase_date.strftime("%Y-%m-%d")

            # Extend search window to 8 days to account for clearing lag
            max_clearing_window = receipt.purchase_date + timedelta(days=8)

            for statement in statements:
                tx_list = list(statement.transactions)
                modified_any_row = False

                for tx in tx_list:
                    if tx.get("inventory_purchase_id") is not None:
                        continue

                    # Safe parsing via adaptive format lookups
                    try:
                        tx_date_obj = self._parse_bank_date(tx["date"])
                    except ValueError:
                        continue  # Log and skip corrupted row formats safely

                    # Absolute value check for the transaction amount (e.g., matching -27.07 against 27.07)
                    amounts_match = abs(abs(tx["amount"]) - receipt.total_amount) < 0.01
                    merchant_matches = receipt.store_name.lower() in tx["description"].lower()

                    if amounts_match and merchant_matches:
                        # Strategy A: It matches within our safe 8-day clearing window
                        within_clearing_window = (
                            receipt.purchase_date <= tx_date_obj <= max_clearing_window
                        )

                        # Strategy B: Explicit matching date token is found embedded inside the raw description text
                        date_token_in_text = (receipt_dot_str in tx["description"]) or (
                            receipt_dash_str in tx["description"]
                        )

                        if within_clearing_window or date_token_in_text:
                            tx["inventory_purchase_id"] = receipt.id
                            receipt.bank_statement_linked = True

                            modified_any_row = True
                            links_established += 1
                            break

                if modified_any_row:
                    statement.transactions = tx_list
                    flag_modified(statement, "transactions")
                    break

        return links_established
