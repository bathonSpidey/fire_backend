import pathlib

from EntryProcessor.SparkasseEntryProcessor import SparkasseEntryProcessor
from Readers.SparkasseReader import SparkasseReader

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
