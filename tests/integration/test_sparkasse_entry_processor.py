import pathlib

from entry_processor.sparkasse_entry_processor import SparkasseEntryProcessor
from readers.sparkasse_reader import SparkasseReader

file_path = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class TestSparkassEntryProcessor:
    def test_read(self):
        reader = SparkasseReader(file_path)
        transactions = reader.read()
        processor = SparkasseEntryProcessor()
        statement = processor.process(transactions)
        assert statement.bank == "Sparkasse"
        assert statement.month == "Apr"
        assert statement.year == 2026
        assert len(statement.transactions) > 0
