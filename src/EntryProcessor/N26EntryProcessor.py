from Models.BankStatement import BankStatement
from Models.BankTransaction import BankTransaction


import re
from datetime import datetime


class N26EntryProcessor:
    def __init__(self):
        self.bank_name = "N26"

    def _parse_amount(self, amt_str: str) -> float:
        # Strips + sign, handles German decimal layout (e.g., "+324,29" -> 324.29)
        return float(amt_str.replace("+", "").replace(".", "").replace(",", "."))

    def _clean_n26_description(self, desc: str) -> str:
        """Extracts only the core transaction meaning from the raw text block."""
        # Matches 'N26 ', grabs everything until ' - transaction ID' or ', paymentId:'
        match = re.search(
            r"N26\s+(.*?)(?:\s*-\s*transaction ID|,\s*paymentId:)", desc, re.IGNORECASE
        )

        if match:
            return match.group(1).strip()
        return desc.split("\n")[-2].strip() if "\n" in desc else desc.strip()

    def process(self, transactions: list[tuple[str, str]]) -> BankStatement:
        start_desc, start_amt = transactions[0]
        _, end_amt = transactions[-1]
        day, month, year = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", start_desc).groups()
        month_name = datetime(int(year), int(month), 1).strftime("%b")
        tx_list = []
        for desc, amt in transactions[1:-1]:
            date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", desc)
            if not date_match:
                continue

            tx_date = date_match.group(0)
            raw_body = desc[date_match.end() :].strip()
            clean_body = self._clean_n26_description(raw_body)

            tx_list.append(
                BankTransaction(
                    date=tx_date, description=clean_body, amount=self._parse_amount(amt)
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
