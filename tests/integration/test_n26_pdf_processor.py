import pathlib

from Readers.N26Reader import N26Reader

file_path = pathlib.Path(__file__).parent / "data" / "n26statement.pdf"


class TestN26PDFProcessor:
    def test_read(self):

        reader = N26Reader(file_path)
        transactions = reader.read()
        assert isinstance(transactions, list)
