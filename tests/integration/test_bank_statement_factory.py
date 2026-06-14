import pathlib

from readers.n26_reader import N26Reader
from readers.sparkasse_reader import SparkasseReader

file_path_n26 = pathlib.Path(__file__).parent / "data" / "n26statement.pdf"
file_path_sparkasse = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class TestBankStatementFactory:
    def test_get_reader_n26(self):
        from readers.bank_reader_factory import BankReaderFactory

        reader = BankReaderFactory.get_reader(file_path_n26)
        assert isinstance(reader, N26Reader)

    def test_get_reader_sparkasse(self):
        from readers.bank_reader_factory import BankReaderFactory

        reader = BankReaderFactory.get_reader(file_path_sparkasse)
        assert isinstance(reader, SparkasseReader)
