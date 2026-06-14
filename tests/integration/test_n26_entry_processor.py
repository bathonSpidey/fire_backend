import pathlib

from EntryProcessor.N26EntryProcessor import N26EntryProcessor
from Readers.N26Reader import N26Reader

file_path = pathlib.Path(__file__).parent / "data" / "n26statement.pdf"


class TestN26EntryProcessor:
    def test_read(self):

        reader = N26Reader(file_path)
        transactions = reader.read()
        processor = N26EntryProcessor()
        statement = processor.process(transactions)
        assert statement.bank == "N26"
        assert statement.month == "Apr"
        assert statement.year == 2026
        assert len(statement.transactions) > 0
