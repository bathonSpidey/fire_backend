import pathlib

from entry_processor.n26_entry_processor import N26EntryProcessor
from readers.n26_reader import N26Reader

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
