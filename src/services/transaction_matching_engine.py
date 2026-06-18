import datetime
import logging
import sys
from datetime import timedelta

from sqlalchemy import extract
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from database.models import DBBankStatement, DBReceipt

# 🛠️ Robust Logger Initialization to force terminal stdout visibility
logger = logging.getLogger("smartory.matching_engine")
logger.setLevel(logging.DEBUG)

# If no handlers exist yet, attach one directly to pipe to standard output
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class TransactionMatchingEngine:
    def __init__(self, db: Session):
        self.db = db

    def _parse_bank_date(self, date_str: str) -> datetime.date:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Could not parse bank statement date format string: '{date_str}'")

    def _get_month_name(self, month_idx: int) -> str:
        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        return months[month_idx - 1]

    def reconcile_orphans(self, target_year: int, target_month: int = None) -> int:
        month_label = f"Month: {target_month}" if target_month else "ALL MONTHS"
        logger.info(f"====== STARTING RECONCILIATION RUN FOR {target_year} ({month_label}) ======")

        # 1. Fetch target receipts (Fixed the 'not' syntax bug by using explicit == False)
        receipt_query = self.db.query(DBReceipt).filter(
            DBReceipt.bank_statement_linked == False,  # noqa: E712
            extract("year", DBReceipt.purchase_date) == target_year,
        )
        if target_month:
            receipt_query = receipt_query.filter(
                extract("month", DBReceipt.purchase_date) == target_month
            )

        unlinked_receipts = receipt_query.all()
        logger.info(f"Found {len(unlinked_receipts)} UNLINKED receipts matching search parameters.")

        # 2. Fetch target bank statements
        statement_query = self.db.query(DBBankStatement).filter(DBBankStatement.year == target_year)
        if target_month:
            month_str = self._get_month_name(target_month)
            statement_query = statement_query.filter(DBBankStatement.month == month_str)

        statements = statement_query.all()
        logger.info(f"Found {len(statements)} relevant Bank Statement containers loaded.")

        links_established = 0

        # 3. Execution Matching Matrix Loops
        for receipt in unlinked_receipts:
            logger.debug(
                f"Evaluating Receipt ID {receipt.id} from '{receipt.store_name}' (€{receipt.total_amount})"
            )

            receipt_dot_str = receipt.purchase_date.strftime("%d.%m.%Y")  # "02.04.2026"
            receipt_dash_str = receipt.purchase_date.strftime("%Y-%m-%d")  # "2026-04-02"
            max_clearing_window = receipt.purchase_date + timedelta(days=8)

            match_found_for_this_receipt = False

            for statement in statements:
                if match_found_for_this_receipt:
                    break

                tx_list = list(statement.transactions)
                modified_any_row = False

                for idx, tx in enumerate(tx_list):
                    if tx.get("inventory_purchase_id") is not None:
                        continue

                    try:
                        tx_date_obj = self._parse_bank_date(tx["date"])
                    except ValueError:
                        continue

                    amounts_match = abs(abs(tx["amount"]) - receipt.total_amount) < 0.01
                    merchant_matches = receipt.store_name.lower() in tx["description"].lower()
                    within_clearing_window = (
                        receipt.purchase_date <= tx_date_obj <= max_clearing_window
                    )
                    date_token_in_text = (receipt_dot_str in tx["description"]) or (
                        receipt_dash_str in tx["description"]
                    )

                    # Trace out evaluation checks for candidates with similar totals or name footprints
                    if merchant_matches or abs(abs(tx["amount"]) - receipt.total_amount) < 5.00:
                        logger.debug(
                            f"   -> Testing against transaction variant: Date={tx['date']} | Amount={tx['amount']}\n"
                            f"      Checks: amounts_match={amounts_match}, merchant_matches={merchant_matches}, "
                            f"within_window={within_clearing_window}, text_token={date_token_in_text}"
                        )

                    if amounts_match and merchant_matches:
                        if within_clearing_window or date_token_in_text:
                            logger.info(
                                f"==== 🎉 MATCH FOUND! Linking Receipt {receipt.id} to Statement {statement.id} Tx #{idx} ===="
                            )
                            tx["inventory_purchase_id"] = receipt.id
                            receipt.bank_statement_linked = True

                            modified_any_row = True
                            match_found_for_this_receipt = True
                            links_established += 1
                            break

                if modified_any_row:
                    statement.transactions = tx_list
                    flag_modified(statement, "transactions")
                    break

        logger.info(
            f"====== RECONCILIATION RUN COMPLETE. Total Links Made: {links_established} ======"
        )
        return links_established
