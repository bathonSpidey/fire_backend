import pathlib

from Readers.SparkasseReader import SparkasseReader

file_path = pathlib.Path(__file__).parent / "data" / "statement.pdf"


class TestSparkasseReader:
    def test_read(self):
        reader = SparkasseReader(file_path)
        transactions = reader.read()
        assert isinstance(transactions, list)
        assert len(transactions) > 0
