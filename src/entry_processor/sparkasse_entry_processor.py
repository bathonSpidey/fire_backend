import re
from datetime import datetime

from models.bank_statement import BankStatement
from models.bank_transaction import BankTransaction


class SparkasseEntryProcessor:
    def __init__(self):
        self.bank_name = "Sparkasse"

    def _parse_amount(self, amt_str: str) -> float:
        return float(amt_str.replace(".", "").replace(",", "."))

    def process(self, transactions: list[tuple[str, str]]) -> BankStatement:
        start_desc, start_amt = transactions[0]
        _, end_amt = transactions[-1]
        day, month, year = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", start_desc).groups()
        target_month = int(month) + 1 if day == "31" else int(month)
        month_name = datetime(int(year), target_month, 1).strftime("%b")
        tx_list = []
        for desc, amt in transactions[1:-1]:
            date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", desc)
            if date_match:
                tx_date = date_match.group(0)
                clean_desc = desc[date_match.end() :].strip()
            else:
                tx_date, clean_desc = "", desc.strip()

            tx_list.append(
                BankTransaction(
                    date=tx_date, description=clean_desc, amount=self._parse_amount(amt)
                )
            )

        return BankStatement(
            month=month_name,
            year=int(year),
            bank=self.bank_name,
            starting_balance=self._parse_amount(start_amt),
            closing_balance=self._parse_amount(end_amt),
            transactions=tx_list,
        )
