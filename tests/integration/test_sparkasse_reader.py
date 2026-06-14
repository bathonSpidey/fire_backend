import pathlib

from pydantic import BaseModel

from Readers.SparkasseReader import SparkasseReader

file_path = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class BankStatement(BaseModel):
    date: str
    bank: str
    balance_last_month: float

    amount: float
    balance: float


# --- Testing Setup (e.g., for pytest) ---


class TestSparkasseReader:
    def test_read(self):
        reader = SparkasseReader(file_path)
        transactions = reader.read()
        assert isinstance(transactions, list)
        assert len(transactions) > 0
