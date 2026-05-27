import pathlib
import sys

import pymupdf
from pydantic import BaseModel

file_path = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class BankStatement(BaseModel):
    date: str
    bank: str
    balance_last_month: float

    amount: float
    balance: float


class SparkasseReader:
    def __init__(self, file_path):
        self.file_path = pathlib.Path(file_path)

    def read(self):
        """Reads the PDF and extracts lines of text from all pages."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")

        extracted_lines = []

        # Open the PDF document
        with pymupdf.open(self.file_path) as doc:
            for page in doc:
                # Extract text as a single string per page
                page_dict = page.get_text("dict")
                page_text = page.get_text("text")

                # Split into lines and clean up empty lines
                lines = [line.strip() for line in page_text.split("\n") if line.strip()]
                extracted_lines.extend(lines)

        return extracted_lines


# --- Testing Setup (e.g., for pytest) ---


class TestSparkasseReader:
    def test_read(self):
        # Initialize the reader with the correct path string
        reader = SparkasseReader(file_path)
        transactions = reader.read()

        # Assert that we actually found text in the document
        assert isinstance(transactions, list)
        assert len(transactions) > 0
