import pathlib
import re
from datetime import datetime

from pydantic import BaseModel

from Readers.SparkasseReader import SparkasseReader

file_path = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class BankTransaction(BaseModel):
    date: str
    description: str
    amount: float


class BankStatement(BaseModel):
    month: str
    year: int
    bank: str
    starting_balance: float
    closing_balance: float
    transactions: list[BankTransaction]


class SparkasseEntryProcessor:
    def __init__(self):
        self.bank_name = "Sparkasse"

    def _parse_amount(self, amt_str: str) -> float:
        return float(amt_str.replace(".", "").replace(",", "."))

    def process(self, transactions: list[tuple[str, str]]) -> BankStatement:
        start_desc, start_amt = transactions[0]
        end_desc, end_amt = transactions[-1]
        
        # 1. Parse statement month metadata
        day, month, year = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", start_desc).groups()
        target_month = int(month) + 1 if day == "31" else int(month)
        month_name = datetime(int(year), target_month, 1).strftime("%b")

        # 2. Parse transactions with robust date extraction
        tx_list = []
        for desc, amt in transactions[1:-1]:
            # re.search finds the date even if preceded by '\n' or spaces
            date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", desc)
            
            if date_match:
                tx_date = date_match.group(0)
                # Split description at the end of the date string to remove it cleanly
                clean_desc = desc[date_match.end():].strip()
            else:
                tx_date, clean_desc = "", desc.strip()
            
            tx_list.append(BankTransaction(
                date=tx_date, 
                description=clean_desc, 
                amount=self._parse_amount(amt)
            ))

        return BankStatement(
            month=month_name,
            year=int(year),
            bank=self.bank_name,
            starting_balance=self._parse_amount(start_amt),
            closing_balance=self._parse_amount(end_amt),
            transactions=tx_list
        )


class TestSparkassEntryProcessor:
    def test_read(self):
        reader = SparkasseReader(file_path)
        transactions = reader.read()
        processor = SparkasseEntryProcessor()
        statement = processor.process(transactions)
        assert statement.bank == "Sparkasse"
        assert statement.month == "Apr"
        assert statement.year == 2026
        assert statement.starting_balance == 38504.50
        assert len(statement.transactions) > 0
